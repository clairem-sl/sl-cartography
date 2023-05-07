# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import math
import multiprocessing as MP
import multiprocessing.managers as MPMgr
import multiprocessing.pool as MPPool
import multiprocessing.shared_memory as MPSharedMem
import queue
import re
import signal
import statistics
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Protocol, cast

import httpx

from retriever import DebugLevel, RetrieverProgress
from retriever.maps.saver import Thresholds, saver
from sl_maptools import CoordType, MapCoord
from sl_maptools.fetchers import RawResult
from sl_maptools.fetchers.map import BoundedMapFetcher

RE_MAPFILENAME: re.Pattern = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_(?P<ts>[0-9-]+)\.jpg$")

SSIM_THRESHOLD: Final[float] = 0.895
MSE_THRESHOLD: Final[float] = 0.01
MAVG_SAMPLES: Final[int] = 5
MIN_COORDS: Final[MapCoord] = MapCoord(0, 0)
MAX_COORDS: Final[MapCoord] = MapCoord(2100, 2100)

CONN_LIMIT: Final[int] = 40
SEMA_SIZE: Final[int] = 120
HTTP2: Final[bool] = True

# BATCH_SIZE should be set to AT LEAST 3x (# of results per BATCH_WAIT period = rslt_per_batch)
# so the number needs to be determined empirically.
# On my laptop, rslt_per_batch is about ~600, so on my laptop
# the number needs to be > 1800; I chose 2000.
# Larger BATCH_SIZE will result in a linearly larger usage of RAM, though.
# So if you don't have much RAM available, reduce BOTH BATCH_SIZE AND BATCH_WAIT
# (E.g., setting BATCH_WAIT to 1.0 will likely reduce rslt_per_batch
# to one-fifth, meaning you can also reduce BATCH_SIZE to one-fifth)
START_BATCH_SIZE: Final[int] = 2000
BATCH_WAIT: Final[float] = 5.0

DEFA_MAPS_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\Maps2\\")
LOCK_NAME: Final[str] = "Maps.lock"
PROG_NAME: Final[str] = "MapsProgress.yaml"
DOMC_NAME: Final[str] = "DominantColors.pkl"

OrigSigINT: signal.Handlers = signal.getsignal(signal.SIGINT)
SaverQueue: MP.Queue
SaveSuccessQueue: MP.Queue
Progress: RetrieverProgress
AbortRequested = asyncio.Event()


def sigint_handler(_, __):
    global AbortRequested
    if not AbortRequested.is_set():
        print("\n### USER INTERRUPT ###")
        print("Cleaning up in-flight job (if any)...", flush=True)
        AbortRequested.set()
    else:
        print(
            "\nUser already interrupted, please wait while retiring in-flight retrievals...",
            flush=True,
        )


class OptionsProtocol(Protocol):
    mapdir: Path
    workers: int
    duration: int
    until: tuple[int, int]
    until_utc: tuple[int, int]
    auto_reset: bool
    force: bool


RE_HHMM = re.compile(r"^(\d{1,2}):(\d{1,2})$")


class HourMinute(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        m = RE_HHMM.match(values)
        if m is None:
            parser.error("Please enter time in 24h HH:MM format!")
        setattr(namespace, self.dest, (int(m.group(1)), int(m.group(2))))


def options() -> OptionsProtocol:
    parser = argparse.ArgumentParser("region_auditor")

    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mapdir", metavar="DIR", type=Path, default=DEFA_MAPS_DIR)
    parser.add_argument(
        "--workers", metavar="N", type=int, default=max(1, MP.cpu_count() - 2), help="Launch N saver workers"
    )
    parser.add_argument(
        "--auto-reset",
        action="store_true",
        help=f"If specified, retriever will wrap up back to maxrow ({MAX_COORDS.y}) upon finishing row 0",
    )
    parser.add_argument("--debug_level", type=DebugLevel, default=DebugLevel.NORMAL)

    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--duration",
        metavar="SECS",
        type=int,
        default=0,
        help=(
            "Dispatch jobs for SECS seconds. When the duration is reached, stop dispatching new jobs "
            "and try to retire still-in-flight jobs, then exit. If less than 1, that means run forever "
            "until interrupted (Ctrl-C)"
        ),
    )
    grp.add_argument(
        "--until",
        metavar="HH:MM",
        action=HourMinute,
        help="Stop dispatching new jobs when wallclock hits this time. WARNING: Does not take DST into account!",
    )
    grp.add_argument(
        "--until-utc",
        metavar="HH:MM",
        action=HourMinute,
        help="Same as --until but using UTC time (no DST problem)",
    )

    _opts = parser.parse_args()

    return cast(OptionsProtocol, _opts)


class SharedMemoryAllocator:
    def __init__(self, manager: MPMgr.SharedMemoryManager):
        self.mgr = manager
        self.allocations: dict[CoordType, MPSharedMem.SharedMemory] = {}

    def new(self, coord: CoordType, data: bytes) -> MPSharedMem.SharedMemory:
        shm = self.mgr.SharedMemory(len(data))
        shm.buf[:] = data
        self.allocations[coord] = shm
        return shm

    def retire(self, coord: CoordType) -> None:
        shm = self.allocations[coord]
        shm.close()
        shm.unlink()
        del self.allocations[coord]


async def async_main(duration: int, shm_allocator: SharedMemoryAllocator):
    global AbortRequested
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(SEMA_SIZE, client, cooked=False, cancel_flag=AbortRequested)

        def make_task(coord: CoordType):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        start = time.monotonic()
        tasks: set[asyncio.Task] = {make_task(coord) async for coord in Progress.abatch(START_BATCH_SIZE)}
        if not tasks:
            print("No unseen jobs, exiting immediately!")
            return

        total = hasmap_count = batch_size = 0
        done_last10: deque[int] = deque(maxlen=MAVG_SAMPLES)
        elapsed_last10: deque[float] = deque(maxlen=MAVG_SAMPLES)
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        while tasks:
            print(f"(+{batch_size}) {len(tasks)} async jobs =>", end=" ")
            start_batch = time.monotonic()
            done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
            elapsed_last10.append(time.monotonic() - start_batch)
            done_last10.append(len(done))
            total += len(done)
            batch_size = int(statistics.median_high(done_last10)) * 3
            c = e = 0
            shown = False
            for c, fut in enumerate(done, start=1):
                if exc := fut.exception():
                    e += 1
                    print(f"\n{fut.get_name()} raised Exception: <{type(exc)}> {exc}")
                    continue
                rslt: None | RawResult = fut.result()
                if rslt is None:
                    continue
                if not rslt.result:
                    Progress.retire(rslt.coord)
                    continue
                if not shown:
                    shown = True
                    print("🌐", end="")
                hasmap_count += 1
                print(f"({rslt.coord.x},{rslt.coord.y})✔", end=" ", flush=True)
                shm = shm_allocator.new(rslt.coord, rslt.result)
                SaverQueue.put(
                    {
                        "coord": rslt.coord,
                        "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                        "shm": shm,
                    }
                )
            try:
                while True:
                    success_coord: MapCoord = SaveSuccessQueue.get_nowait()
                    Progress.retire(success_coord)
                    shm_allocator.retire(success_coord)
            except queue.Empty:
                pass
            if c:
                Progress.save()
                if e == c:
                    print("\nLast batch all raised Exceptions!")
                    print("Cancelling the rest of the tasks...")
                    for t in pending_tasks:
                        t.cancel()
            if not shown:
                print("No maps retrieved", end="")
            elapsed = time.monotonic() - start
            avg_rate = sum(done_last10) / sum(elapsed_last10)
            print(
                f"\n  {elapsed:_.2f}s since start, {total:_} coords scanned "
                f"(mavg. {avg_rate:.2f} r/s), {hasmap_count} maps retrieved"
            )
            tasks = pending_tasks
            if elapsed >= duration:
                AbortRequested.set()
            if not AbortRequested.is_set() and (2 * len(tasks)) < batch_size:
                async for coord in Progress.abatch(batch_size):
                    tasks.add(make_task(coord))


def main(
    mapdir: Path,
    duration: int,
    until: tuple[int, int],
    until_utc: tuple[int, int],
    auto_reset: bool,
    workers: int,
    force: bool,
    debug_level: DebugLevel,
):
    global Progress, SaverQueue, SaveSuccessQueue
    mapdir.mkdir(parents=True, exist_ok=True)

    lockf: Path = mapdir / LOCK_NAME
    if not force:
        try:
            lockf.touch(exist_ok=False)
        except FileExistsError:
            print(f"Lock file {lockf} exists!", file=sys.stderr)
            print("You must not run multiple retrievers at the same time.", file=sys.stderr)
            print(
                "If no other retriever is running, delete the lock file to continue.",
                file=sys.stderr,
            )
            sys.exit(1)

    nao = datetime.now()
    if duration > 0:
        dur = duration
    elif until:
        hh, mm = until
        unt = nao.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if unt < nao:
            unt = unt + timedelta(days=1)
        dur = (unt - nao).seconds
    elif until_utc:
        hh, mm = until_utc
        nao = nao.astimezone(timezone.utc)
        unt = nao.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if unt < nao:
            unt = unt + timedelta(days=1)
        dur = (unt - nao).seconds
    else:
        dur = math.inf

    progress_file = mapdir / PROG_NAME
    Progress = RetrieverProgress(progress_file, auto_reset=auto_reset, min_coord=MIN_COORDS, max_coord=MAX_COORDS)
    if Progress.outstanding_count:
        print(f"{Progress.outstanding_count} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")
        if Progress.next_y < 0:
            print("No rows left to process.")
            print(f"Delete the file {progress_file} to reset. (Or specify --auto-reset)")
    print(f"Next coordinate: {Progress.next_coordinate}")

    with MP.Manager() as manager, MPMgr.SharedMemoryManager() as shm_manager:
        print("Starting saver worker...", end="", flush=True)
        SaverQueue = MP.Queue()
        SaveSuccessQueue = MP.Queue()
        saved_coords: dict[CoordType, None] = manager.dict()
        worker_state: dict[str, tuple[str, Path | None]] = manager.dict()
        possibly_changed: dict[CoordType, None] = manager.dict()
        shm_allocator = SharedMemoryAllocator(shm_manager)

        _mapfilesets: dict[CoordType, list[Path]] = {}
        m: re.Match
        flist: list[Path]
        for mapfile in sorted(mapdir.glob("*.jpg")):
            if (m := RE_MAPFILENAME.match(mapfile.name)) is None:
                continue
            coord = (int(m.group("x")), int(m.group("y")))
            _mapfilesets.setdefault(coord, []).append(mapfile)
        mapfilesets = manager.dict(_mapfilesets)

        thresholds = Thresholds(MSE=MSE_THRESHOLD, SSIM=SSIM_THRESHOLD)
        saver_args = (
            mapdir,
            mapfilesets,
            SaverQueue,
            SaveSuccessQueue,
            saved_coords,
            worker_state,
            debug_level,
            thresholds,
            possibly_changed,
        )
        pool: MPPool.Pool
        with MP.Pool(workers, initializer=saver, initargs=saver_args) as pool:
            while sum(1 for v, _ in worker_state.values() if v == "idle") < workers:
                time.sleep(1)

            print("started.\nDispatching async fetchers!", flush=True)
            try:
                signal.signal(signal.SIGINT, sigint_handler)
                asyncio.run(async_main(dur, shm_allocator))
            finally:
                time.sleep(1)
                signal.signal(signal.SIGINT, OrigSigINT)

            print("Closing the pool, preventing new workers from spawning ... ", end="", flush=True)
            pool.close()
            print("closed.\nCurrent worker states:")
            for n, s in worker_state.items():
                print(f"  {n}: {s}")
                if s != "ended":
                    SaverQueue.put(None)
            print("Waiting for workers to join ... ", end="", flush=True)
            pool.join()
            print("joined. \nClosing SaverQueue ... ", end="", flush=True)
            SaverQueue.close()
            SaverQueue.join_thread()
            print("closed")
            try:
                print("Flushing SaveSuccess queue ... ", end="", flush=True)
                while True:
                    coord = SaveSuccessQueue.get(timeout=5)
                    Progress.retire(coord)
                    shm_allocator.retire(coord)
            except queue.Empty:
                pass
            finally:
                SaveSuccessQueue.close()
                SaveSuccessQueue.join_thread()
                print("flushed")
                Progress.save()
            with (mapdir / "PossiblyChanged.txt").open("wt") as fout:
                for coord in sorted(possibly_changed.keys()):
                    print(coord, file=fout)
    print(f"{Progress.outstanding_count:_} outstanding jobs left. Last dispatched coordinate: {Progress.last_dispatch}")

    lockf.unlink(missing_ok=True)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
    if AbortRequested.is_set():
        print("\nAborted by user.")
