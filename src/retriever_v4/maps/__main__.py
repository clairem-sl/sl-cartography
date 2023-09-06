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
from typing import TYPE_CHECKING, Final, Optional, Protocol, cast

import httpx

from retriever_v4 import (
    DebugLevel,
    RetrieverApplication,
    RetrieverProgress,
    dispatch_fetcher,
)
from retriever_v4.maps.saver import saver
from sl_maptools import CoordType, MapCoord
from sl_maptools.fetchers.map import BoundedMapFetcher
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader, SLMapToolsConfig, handle_sigint

if TYPE_CHECKING:
    from sl_maptools.fetchers import RawResult

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
AbortRequested = asyncio.Event()


class RetrieverMapsOptions(Protocol):
    """Prototype of module-specific options returned by get_options"""
    
    mapdir: Path
    workers: int
    auto_reset: bool
    debug_level: DebugLevel
    coordfile: Optional[Path]
    areas: list[str]
    duration: int


class OptionsProtocol(RetrieverMapsOptions, RetrieverApplication.Options, Protocol):
    """Prototype of options"""
    
    pass


def get_options() -> OptionsProtocol:
    """Get options from CLI"""
    parser = argparse.ArgumentParser("region_auditor")

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

    RetrieverApplication.add_options(parser)

    _opts = cast(OptionsProtocol, parser.parse_args())
    _opts.duration = RetrieverApplication.calc_duration(_opts)
    return _opts


class SharedMemoryAllocator:
    """A thin wrapper to track shared memory and retire"""
    
    def __init__(self, manager: MPMgr.SharedMemoryManager) -> None:
        """
        Instatiates a SharedMemoryAllocator
        
        :param manager: A SharedMemoryManager from multiprocessing
        """
        self.mgr = manager
        self.allocations: dict[CoordType, MPSharedMem.SharedMemory] = {}

    def new(self, coord: CoordType, data: bytes) -> MPSharedMem.SharedMemory:
        """
        Creates a new SharedMemory containing specified data

        :param coord: The coordinate, used as SharedMemory ID
        :param data: The blob to be put into the SharedMemory
        """
        shm = self.mgr.SharedMemory(len(data))
        shm.buf[:] = data
        self.allocations[coord] = shm
        return shm

    def retire(self, coord: CoordType) -> None:
        """
        Retires a SharedMemory

        :param coord: The ID of SharedMemory to retire
        """
        shm = self.allocations[coord]
        shm.close()
        shm.unlink()
        del self.allocations[coord]


async def async_main(
    progress: RetrieverProgress,
    opts: OptionsProtocol,
    shm_allocator: SharedMemoryAllocator,
    saver_queue: MP.Queue,
    save_success_queue: MP.Queue,
) -> None:
    """Perform async retrieval"""
    global AbortRequested  # noqa: PLW0602
    duration: int = opts.duration
    min_batch_size: int = opts.min_batch_size
    abort_low_rps: int = opts.abort_low_rps

    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(CONN_LIMIT * 3, client, cooked=False, cancel_flag=AbortRequested)
        shown = False

        def make_task(coord: CoordType) -> asyncio.Task:
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        def pre_batch() -> None:
            nonlocal shown
            shown = False

        def process_result(fut_result: None | RawResult) -> bool:
            nonlocal shown
            if fut_result is None:
                return False
            if not fut_result.result:
                progress.retire(fut_result.coord)
                return False
            if not shown:
                shown = True
                print("🌐", end="")
            print(f"({fut_result.coord.x},{fut_result.coord.y})✔", end=" ", flush=True)
            saver_queue.put(
                {
                    "coord": fut_result.coord,
                    "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                    "shm": shm_allocator.new(fut_result.coord, fut_result.result),
                }
            )
            return True

        def post_batch() -> None:
            if not shown:
                print("No maps retrieved", end="")
            try:
                while True:
                    coord: MapCoord = save_success_queue.get_nowait()
                    progress.retire(coord)
                    shm_allocator.retire(coord)
            except queue.Empty:
                pass

        await dispatch_fetcher(
            progress=progress,
            duration=duration,
            taskmaker=make_task,
            result_handler=process_result,
            pre_batch=pre_batch,
            post_batch=post_batch,
            abort_event=AbortRequested,
            min_batch_size=min_batch_size,
            abort_low_rps=abort_low_rps,
        )


def mp_main(
    opts: OptionsProtocol,
    progress: RetrieverProgress,
    manager: MP.Manager,
    shm_manager: MPMgr.SharedMemoryManager,
) -> None:
    """Perform multiprocessing retrieval"""
    print("Starting saver worker...", end="", flush=True)
    saver_queue = MP.Queue()
    save_success_queue = MP.Queue()
    saved_coords: dict[CoordType, None] = manager.dict()
    worker_state: dict[str, tuple[str, Path | None]] = manager.dict()
    possibly_changed: dict[CoordType, None] = manager.dict()
    shm_allocator = SharedMemoryAllocator(shm_manager)

    saver_args = (
        opts.mapdir,
        saver_queue,
        save_success_queue,
        saved_coords,
        worker_state,
        opts.debug_level,
    )
    pool: MPPool.Pool
    with MP.Pool(opts.workers, initializer=saver, initargs=saver_args) as pool:
        while sum(1 for v, _ in worker_state.values() if v == "idle") < opts.workers:
            time.sleep(1)

        print("started.\nDispatching async fetchers!", flush=True)
        with handle_sigint(AbortRequested):
            asyncio.run(
                async_main(
                    progress,
                    opts,
                    shm_allocator,
                    saver_queue,
                    save_success_queue,
                )
            )

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
                saver_queue.put(None)
        print("Waiting for workers to join ... ", end="", flush=True)
        pool.join()
        print("joined. \nClosing SaverQueue ... ", end="", flush=True)
        saver_queue.close()
        saver_queue.join_thread()
        print("closed")
        try:
            print("Flushing SaveSuccess queue ... ", end="", flush=True)
            while True:
                coord = save_success_queue.get(timeout=5)
                progress.retire(coord)
                shm_allocator.retire(coord)
        except queue.Empty:
            pass
        finally:
            save_success_queue.close()
            save_success_queue.join_thread()
            print("flushed")
            progress.save()
        with (opts.mapdir / "PossiblyChanged.txt").open("wt") as fout:
            for coord in sorted(possibly_changed.keys()):
                print(coord, file=fout)


def main(
    opts: OptionsProtocol,
) -> None:
    """The main function"""
    progress_file = opts.mapdir / Config.maps.progress
    progress = RetrieverProgress(progress_file, auto_reset=opts.auto_reset)
    if progress.outstanding_count:
        print(f"{progress.outstanding_count} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")

    if opts.coordfile and opts.coordfile.exists():
        with opts.coordfile.open("rt") as fin:
            for ln in fin:
                ln = ln.strip()
                if not ln:
                    continue
                x, y = ln.split(",")
                progress.add((int(x), int(y)))

    if opts.areas:
        cs_anames = {k.casefold(): k for k in KNOWN_AREAS.keys()}
        want_areas: set[str] = {
            cs_anames[a1] for area in opts.areas for a1 in map(str.casefold, area.split(",")) if a1 in cs_anames
        }
        for aname in want_areas:
            for coord in KNOWN_AREAS[aname].bounding_box.xy_iterator():
                progress.add(coord)

    print(f"Next coordinate: {progress.next_coordinate}")
    if progress.next_coordinate[1] < 0:
        print("No rows left to process.")
        print(f"Delete the file {progress_file} to reset. (Or specify --auto-reset)")
        return

    with MP.Manager() as manager, MPMgr.SharedMemoryManager() as shm_manager:
        mp_main(opts, progress, manager, shm_manager)
    print(f"{progress.outstanding_count:_} outstanding jobs left. Last dispatched coordinate: {progress.last_dispatch}")
    if AbortRequested.is_set():
        print("\nAborted by user.")


if __name__ == "__main__":
    options = get_options()
    lock_file = options.mapdir / Config.maps.lock
    log_file = options.mapdir / Config.maps.log
    with RetrieverApplication(lock_file=lock_file, log_file=lock_file, force=options.force) as app:
        main(options)
