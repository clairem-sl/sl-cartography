# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import io
import math
import multiprocessing as MP
import multiprocessing.managers as MPMgr
import multiprocessing.pool as MPPool
import multiprocessing.shared_memory as MPSharedMem
# import multiprocessing.synchronize as MPSync
# import pickle
import queue
import re
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Final, TypedDict, cast, Protocol, Any

import httpx
import numpy as np
from PIL import Image
from skimage.metrics import (
    mean_squared_error as mse,
    structural_similarity as ssim
)

from retriever import RetrieverProgress
from sl_maptools import MapCoord
from sl_maptools.fetchers import RawResult
# from sl_maptools.image_processing import calculate_dominant_colors, FASCIA_COORDS, RGBTuple
from sl_maptools.fetchers.map import BoundedMapFetcher


RE_MAPFILENAME: re.Pattern = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_(?P<ts>[0-9-]+)\.jpg$")

SSIM_THRESHOLD: Final[float] = 0.98
MSE_THRESHOLD: Final[float] = 0.01
MIN_COORDS: Final[MapCoord] = MapCoord(0, 0)
MAX_COORDS: Final[MapCoord] = MapCoord(2100, 2100)

CONN_LIMIT: Final[int] = 40
SEMA_SIZE: Final[int] = 120
HTTP2: Final[bool] = True
# CONN_LIMIT = 20
# SEMA_SIZE = 100
# HTTP2 = True

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
SharedMemoryAllocations: dict[tuple[int, int], MPSharedMem.SharedMemory] = {}


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
    # nodom: bool
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


class DebugLevel(IntEnum):
    DISABLED = 0
    NORMAL = 1
    DETAILED = 2


def options() -> OptionsProtocol:
    parser = argparse.ArgumentParser("region_auditor")

    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mapdir", metavar="DIR", type=Path, default=DEFA_MAPS_DIR)
    # parser.add_argument("--nodom", action="store_true", help="If specified, do not calculate dominant color")
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


class QJob(TypedDict):
    coord: MapCoord
    tsf: str
    shm: MPSharedMem.SharedMemory


def saver(
    mapdir: Path,
    mapfilesets: dict[tuple[int, int], list[Path]],
    save_queue: MP.Queue,
    success_queue: MP.Queue,
    saved: dict[MapCoord, Any],
    worker_state: dict[str, tuple[str, str | None]],
    debug_level: DebugLevel,
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    mapdir.mkdir(parents=True, exist_ok=True)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"SaverWorker-{num}"
    MP.current_process().name = myname
    targf: Path | None = None

    def _setstate(state: str, with_targ: bool = True):
        if with_targ and targf:
            worker_state[myname] = state, targf.name
        else:
            worker_state[myname] = state, None

    img: Image.Image | None = None
    while True:
        _setstate("idle", False)
        if save_queue.empty():
            time.sleep(1)
            continue
        item = save_queue.get()
        if item is None:
            break

        _setstate("got_job", False)
        regmap: QJob = cast(QJob, item)
        coord: MapCoord = regmap["coord"]
        shm: MPSharedMem.SharedMemory = regmap["shm"]
        if coord in saved:
            shm.close()
            continue
        blob = cast(bytes, shm.buf)
        try:
            try:
                tsf = regmap["tsf"]
                targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
                _setstate("saving")
                with targf.open("wb") as fout:
                    fout.write(blob)
            except Exception:
                raise

            saved[coord] = None
            counter = len(saved)
            if debug_level > DebugLevel.DISABLED:
                print(f"💾", end="", flush=True)
                if debug_level >= DebugLevel.DETAILED:
                    print(f"[{counter}]", end="", flush=True)

            _setstate("decoding")
            with io.BytesIO(blob) as bio:
                img: Image.Image = Image.open(bio)
                img.load()

            # if dominant_colors is not None:
            #     domc: dict[int, list[RGBTuple]] = {}
            #     for fasz in FASCIA_COORDS:
            #         domc[fasz] = calculate_dominant_colors(img, fasz)
            #     dominant_colors[tuple(coord)] = domc

            # Prune older file of same coordinate if really similar
            if (coordfiles := mapfilesets.get(coord)) is None:
                continue
            _setstate("converting1")
            # noinspection PyTypeChecker
            f1_arr = np.asarray(img.convert("L"))
            f2_img: Image.Image | None = None
            do_delete: bool = False
            while coordfiles:
                f2 = coordfiles[-1]
                try:
                    _setstate("fetching")
                    with f2.open("rb") as fin:
                        f2_img = Image.open(fin)
                        f2_img.load()
                    _setstate("converting2")
                    # noinspection PyTypeChecker
                    f2_arr = np.asarray(f2_img.convert("L"))
                    # Image similarity test using Structural Similarity Index,
                    # see https://pyimagesearch.com/2014/09/15/python-compare-two-images/
                    _setstate("comparing_mse")
                    mse_result = mse(f1_arr, f2_arr)
                    if mse_result < MSE_THRESHOLD:
                        do_delete = True
                        _setstate("deleting_mse")
                    else:
                        _setstate("comparing_ssim")
                        ssim_result = ssim(f1_arr, f2_arr)
                        if ssim_result > SSIM_THRESHOLD:
                            do_delete = True
                            _setstate("deleting_ssim")
                    if do_delete:
                        f2.unlink()
                        coordfiles.pop()
                        if debug_level > DebugLevel.DISABLED:
                            print(f"❌", end="", flush=True)
                            if debug_level >= DebugLevel.DETAILED:
                                print(f"[{counter}]", end="", flush=True)
                        do_delete = False
                    else:
                        break
                except FileNotFoundError:
                    if coordfiles:
                        coordfiles.pop()
                except Exception as e:
                    print(f"\nERR: {myname}:{type(e)}:{e}")
                    raise
                finally:
                    if f2_img is not None:
                        f2_img.close()
            _setstate("resolving")
            coordfiles.append(targf)
            mapfilesets[coord] = coordfiles
            success_queue.put(coord)
        except Exception as e:
            print(f"\nERR: {myname}:{type(e)}:{e}")
            raise
        finally:
            _setstate("cleaning")
            shm.close()
            if img is not None:
                img.close()
    _setstate("ended")


async def async_main(duration: int, shm_mgr: MPMgr.SharedMemoryManager):
    global AbortRequested
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(SEMA_SIZE, client, cooked=False, cancel_flag=AbortRequested)
        # coords = [MapCoord(x, y) for x in range(950, 1050) for y in range(950, 1050)]

        def make_task(coord: tuple[int, int]):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        tasks: set[asyncio.Task] = {make_task(coord) async for coord in Progress.abatch(START_BATCH_SIZE)}
        if not tasks:
            print("No unseen jobs, exiting immediately!")
            return

        start = time.monotonic()
        total = hasmap_count = batch_size = 0
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        while tasks:
            print(f"{len(tasks)} async jobs =>", end=" ")
            done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
            total += len(done)
            batch_size = max(batch_size, len(done) * 3)
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
                if rslt.result:
                    shown = True
                    hasmap_count += 1
                    print(f"({rslt.coord.x},{rslt.coord.y})✔", end=" ")
                    shm = shm_mgr.SharedMemory(len(rslt.result))
                    shm.buf[:] = rslt.result
                    SaverQueue.put(
                        {
                            "coord": rslt.coord,
                            "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                            "shm": shm,
                        }
                    )
                    SharedMemoryAllocations[rslt.coord] = shm
                else:
                    await Progress.aretire(rslt.coord)
            try:
                while True:
                    success_coord: MapCoord = SaveSuccessQueue.get_nowait()
                    await Progress.aretire(success_coord)
                    shm = SharedMemoryAllocations[success_coord]
                    shm.close()
                    shm.unlink()
                    del SharedMemoryAllocations[success_coord]
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
            avg_rate = total / elapsed
            print(
                f"\n  {elapsed:_.2f}s since start, {total:_} coords scanned "
                f"(avg. {avg_rate:.2f} r/s), {hasmap_count} maps retrieved"
            )
            # print(f"  using {fetcher.seen_http_vers}")
            tasks = pending_tasks
            if elapsed >= duration:
                AbortRequested.set()
            if not AbortRequested.is_set():
                if (2 * len(tasks)) < batch_size:
                    async for coord in Progress.abatch(batch_size):
                        tasks.add(make_task(coord))


def main(
    mapdir: Path,
    duration: int,
    until: tuple[int, int],
    until_utc: tuple[int, int],
    auto_reset: bool,
    # nodom: bool,
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
            print("You must not run multiple audits at the same time.", file=sys.stderr)
            print(
                "If no other audit is running, delete the lock file to continue.",
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
        print(f"Next coordinate: {Progress.next_coordinate}")
    else:
        print("No outstanding jobs from last session.")
        if Progress.next_y < 0:
            print("No rows left to process.")
            print(f"Delete the file {progress_file} to reset. (Or specify --auto-reset)")

    with MP.Manager() as manager, MPMgr.SharedMemoryManager() as shm_manager:
        print("Starting saver worker...", end="", flush=True)
        SaverQueue = MP.Queue()
        SaveSuccessQueue = MP.Queue()
        saved = manager.dict()
        worker_state = manager.dict()

        _mapfilesets: dict[tuple[int, int], list[Path]] = {}
        m: re.Match
        flist: list[Path]
        for mapfile in sorted(mapdir.glob("*.jpg")):
            if (m := RE_MAPFILENAME.match(mapfile.name)) is None:
                continue
            coord = (int(m.group("x")), int(m.group("y")))
            _mapfilesets.setdefault(coord, []).append(mapfile)
        mapfilesets = manager.dict(_mapfilesets)

        saver_args = (mapdir, mapfilesets, SaverQueue, SaveSuccessQueue, saved, worker_state, debug_level)
        pool: MPPool.Pool
        with MP.Pool(workers, initializer=saver, initargs=saver_args) as pool:

            print("started.\nDispatching async fetchers!", flush=True)
            try:
                signal.signal(signal.SIGINT, sigint_handler)
                asyncio.run(async_main(dur, shm_manager))
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
                    shm = SharedMemoryAllocations[coord]
                    shm.close()
                    shm.unlink()
                    del SharedMemoryAllocations[coord]
                    Progress.retire(coord)
            except queue.Empty:
                pass
            finally:
                SaveSuccessQueue.close()
                SaveSuccessQueue.join_thread()
                print("flushed")
                Progress.save()
    print(f"{Progress.outstanding_count:_} outstanding jobs left. Last dispatched coordinate: {Progress.last_dispatch}")

    lockf.unlink(missing_ok=True)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
    if AbortRequested.is_set():
        print("\nAborted by user.")
