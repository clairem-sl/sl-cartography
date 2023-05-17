# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import multiprocessing as MP
import multiprocessing.managers as MPMgr
import multiprocessing.pool as MPPool
import multiprocessing.shared_memory as MPSharedMem
import queue
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Final, Optional, Protocol, cast

import httpx

from retriever_v4 import (
    DebugLevel,
    RetrieverApplication,
    RetrieverProgress,
    TimeOptions,
    add_timeoptions,
    calc_duration,
    dispatch_fetcher,
    handle_sigint,
)
from retriever_v4.maps.saver import Thresholds, saver
from sl_maptools import CoordType, MapCoord
from sl_maptools.fetchers import RawResult
from sl_maptools.fetchers.map import BoundedMapFetcher
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import inventorize_maps_all

SSIM_THRESHOLD: Final[float] = 0.895
MSE_THRESHOLD: Final[float] = 0.01
MAVG_SAMPLES: Final[int] = 5

CONN_LIMIT: Final[int] = 80
# SEMA_SIZE: Final[int] = 180
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

Config: SLMapToolsConfig = ConfigReader("config.toml")

OrigSigINT: signal.Handlers = signal.getsignal(signal.SIGINT)
SaverQueue: MP.Queue
SaveSuccessQueue: MP.Queue
Progress: RetrieverProgress

AbortRequested = asyncio.Event()


class RetrieverMapsOptions(Protocol):
    mapdir: Path
    workers: int
    auto_reset: bool
    force: bool
    debug_level: DebugLevel
    min_batch_size: int
    abort_low_rps: int
    coordfile: Optional[Path]
    areas: list[str]


class OptionsProtocol(RetrieverMapsOptions, TimeOptions, Protocol):
    pass


def get_options() -> OptionsProtocol:
    parser = argparse.ArgumentParser("region_auditor")

    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mapdir", metavar="DIR", type=Path, default=Path(Config.maps.dir))
    parser.add_argument(
        "--workers",
        metavar="N",
        type=int,
        default=max(1, MP.cpu_count() - 2),
        help="Launch N saver workers",
    )
    parser.add_argument(
        "--auto-reset",
        action="store_true",
        help=(
            f"If specified, retriever will wrap up back to maxrow "
            f"({RetrieverProgress.DEFA_MAX_COORD[1]}) upon finishing row 0"
        ),
    )
    parser.add_argument("--debug_level", type=DebugLevel, default=DebugLevel.NORMAL)
    parser.add_argument(
        "--min-batch-size",
        metavar="N",
        type=int,
        default=0,
        help="Batch size will not go lower than this",
    )
    parser.add_argument(
        "--abort-low-rps",
        metavar="N",
        type=int,
        default=-1,
        help="If rps drops below this for some time, abort",
    )
    parser.add_argument(
        "--coordfile",
        metavar="FILE",
        type=Path,
        help=(
            "If specified, fetch coordinates from FILE, in addition to prior progress. "
            "Contents of the file must by X,Y pairs, one per line."
        ),
    )
    parser.add_argument(
        "--areas",
        metavar="AREA_LIST",
        type=str,
        nargs="+",
        help="Space- and/or comma-separated list of areas to retrieve, in addition to prior progress.",
    )

    add_timeoptions(parser)

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


async def async_main(
    duration: int,
    min_batch_size: int,
    abort_low_rps: int,
    shm_allocator: SharedMemoryAllocator,
):
    global AbortRequested
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(CONN_LIMIT * 3, client, cooked=False, cancel_flag=AbortRequested)
        shown = False

        def make_task(coord: CoordType):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        def pre_batch():
            nonlocal shown
            shown = False

        def process_result(fut_result: None | RawResult) -> bool:
            nonlocal shown
            if fut_result is None:
                return False
            if not fut_result.result:
                Progress.retire(fut_result.coord)
                return False
            if not shown:
                shown = True
                print("🌐", end="")
            print(f"({fut_result.coord.x},{fut_result.coord.y})✔", end=" ", flush=True)
            SaverQueue.put(
                {
                    "coord": fut_result.coord,
                    "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                    "shm": shm_allocator.new(fut_result.coord, fut_result.result),
                }
            )
            return True

        def post_batch():
            if not shown:
                print("No maps retrieved", end="")
            try:
                while True:
                    coord: MapCoord = SaveSuccessQueue.get_nowait()
                    Progress.retire(coord)
                    shm_allocator.retire(coord)
            except queue.Empty:
                pass

        await dispatch_fetcher(
            progress=Progress,
            duration=duration,
            taskmaker=make_task,
            result_handler=process_result,
            pre_batch=pre_batch,
            post_batch=post_batch,
            abort_event=AbortRequested,
            min_batch_size=min_batch_size,
            abort_low_rps=abort_low_rps,
        )


def main(
    opts: OptionsProtocol,
):
    global Progress, SaverQueue, SaveSuccessQueue

    dur = calc_duration(opts)
    progress_file = opts.mapdir / Config.maps.progress
    Progress = RetrieverProgress(progress_file, auto_reset=opts.auto_reset)
    if Progress.outstanding_count:
        print(f"{Progress.outstanding_count} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")

    if opts.coordfile and opts.coordfile.exists():
        with opts.coordfile.open("rt") as fin:
            for ln in fin:
                ln = ln.strip()
                if not ln:
                    continue
                x, y = ln.split(",")
                Progress.add((int(x), int(y)))

    if opts.areas:
        cs_anames = {k.casefold(): k for k in KNOWN_AREAS.keys()}
        want_areas: set[str] = {
            cs_anames[a1] for area in opts.areas for a1 in map(str.casefold, area.split(",")) if a1 in cs_anames
        }
        for aname in want_areas:
            for coord in KNOWN_AREAS[aname].xy_iterator():
                Progress.add(coord)

    print(f"Next coordinate: {Progress.next_coordinate}")
    if Progress.next_coordinate[1] < 0:
        print("No rows left to process.")
        print(f"Delete the file {progress_file} to reset. (Or specify --auto-reset)")
        return

    with MP.Manager() as manager, MPMgr.SharedMemoryManager() as shm_manager:
        print("Starting saver worker...", end="", flush=True)
        SaverQueue = MP.Queue()
        SaveSuccessQueue = MP.Queue()
        saved_coords: dict[CoordType, None] = manager.dict()
        worker_state: dict[str, tuple[str, Path | None]] = manager.dict()
        possibly_changed: dict[CoordType, None] = manager.dict()
        shm_allocator = SharedMemoryAllocator(shm_manager)

        map_inventory = manager.dict(inventorize_maps_all(opts.mapdir))

        thresholds = Thresholds(MSE=MSE_THRESHOLD, SSIM=SSIM_THRESHOLD)
        saver_args = (
            opts.mapdir,
            map_inventory,
            SaverQueue,
            SaveSuccessQueue,
            saved_coords,
            worker_state,
            opts.debug_level,
            thresholds,
            possibly_changed,
        )
        pool: MPPool.Pool
        with MP.Pool(opts.workers, initializer=saver, initargs=saver_args) as pool:
            while sum(1 for v, _ in worker_state.values() if v == "idle") < opts.workers:
                time.sleep(1)

            print("started.\nDispatching async fetchers!", flush=True)
            with handle_sigint(AbortRequested):
                asyncio.run(async_main(dur, opts.min_batch_size, opts.abort_low_rps, shm_allocator))

            print(
                "Closing the pool, preventing new workers from spawning ... ",
                end="",
                flush=True,
            )
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
            with (opts.mapdir / "PossiblyChanged.txt").open("wt") as fout:
                for coord in sorted(possibly_changed.keys()):
                    print(coord, file=fout)
    print(f"{Progress.outstanding_count:_} outstanding jobs left. Last dispatched coordinate: {Progress.last_dispatch}")
    if AbortRequested.is_set():
        print("\nAborted by user.")


if __name__ == "__main__":
    options = get_options()
    lock_file = options.mapdir / Config.maps.lock
    log_file = options.mapdir / Config.maps.log
    with RetrieverApplication(lock_file=lock_file, log_file=lock_file) as app:
        main(options)
