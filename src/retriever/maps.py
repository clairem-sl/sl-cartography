# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import math
import multiprocessing as MP
import queue
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Final, TypedDict, cast, Protocol

import httpx
from PIL import Image

from retriever import RetrieverProgress
from sl_maptools import MapCoord, MapRegion
from sl_maptools.fetchers.map import BoundedMapFetcher

# from sl_maptools.bb_fetcher import BoundedNameFetcher, CookedTile


MIN_X: Final[int] = 0
MAX_X: Final[int] = 2100

CONN_LIMIT: Final[int] = 40
SEMA_SIZE: Final[int] = 100
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
BATCH_SIZE: Final[int] = 2000
BATCH_WAIT: Final[float] = 5.0

DEFA_MAPS_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\Maps2\\")
LOCK_NAME: Final[str] = "Maps.lock"
PROG_NAME: Final[str] = "MapsProgress.yaml"


SaverQueue: MP.Queue
SaveSuccessQueue: MP.Queue
Progress: RetrieverProgress
AbortRequested = asyncio.Event()


def sigint(_, __):
    global AbortRequested
    if not AbortRequested.is_set():
        print("\n### USER INTERRUPT ###")
        print("Cleaning up in-flight job (if any)...", flush=True)
        AbortRequested.set()
    else:
        print("\nUser already interrupted, please wait while retiring in-flight retrievals...", flush=True)


class OptionsProtocol(Protocol):
    mapdir: Path
    duration: int
    no_auto_reset: bool


def options() -> OptionsProtocol:
    parser = argparse.ArgumentParser("region_auditor")

    parser.add_argument("--mapdir", metavar="DIR", type=Path, default=DEFA_MAPS_DIR)
    parser.add_argument(
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
    parser.add_argument(
        "--no-auto-reset",
        action="store_true",
        help="If specified, retriever will not wrap up back to maxrow (2100) upon finishing row 0",
    )

    _opts = parser.parse_args()

    return cast(OptionsProtocol, _opts)


class QJob(TypedDict):
    coord: MapCoord
    tsf: str
    image: Image.Image


def saver(mapdir: Path, save_queue: MP.Queue, success_queue: MP.Queue):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    mapdir.mkdir(parents=True, exist_ok=True)
    while True:
        if save_queue.empty():
            time.sleep(1)
            continue
        item = save_queue.get()
        if item is None:
            break
        regmap: QJob = cast(QJob, item)
        try:
            coord = regmap["coord"]
            tsf = regmap["tsf"]
            targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
            regmap["image"].save(targf)
            print("💾", end="", flush=True)
            success_queue.put(coord)
        except Exception:
            raise
    success_queue.put(None)


async def async_main(duration: int):
    global AbortRequested
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(SEMA_SIZE, client, cooked=True, cancel_flag=AbortRequested)
        # coords = [MapCoord(x, y) for x in range(950, 1050) for y in range(950, 1050)]

        def make_task(coord: tuple[int, int]):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        tasks: set[asyncio.Task] = {make_task(coord) async for coord in Progress.abatch(BATCH_SIZE)}
        if not tasks:
            print("No unseen jobs, exiting immediately!")
            return

        start = time.monotonic()
        total = 0
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        while tasks:
            print(f"{len(tasks)} async jobs =>", end=" ")
            done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
            total += len(done)
            c = e = 0
            for c, fut in enumerate(done, start=1):
                if exc := fut.exception():
                    e += 1
                    print(f"\n{fut.get_name()} raised Exception: <{type(exc)}> {exc}")
                    continue
                rslt: MapRegion = fut.result()
                if rslt is None:
                    continue
                if rslt.image:
                    print(f"({rslt.coord.x},{rslt.coord.y})✔", end=" ")
                    SaverQueue.put(
                        {
                            "coord": rslt.coord,
                            "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                            "image": rslt.image,
                        }
                    )
                else:
                    await Progress.aretire(rslt.coord)
            try:
                while True:
                    success_coord: MapCoord = SaveSuccessQueue.get_nowait()
                    await Progress.aretire(success_coord)
            except queue.Empty:
                pass
            if c:
                Progress.save()
                if e == c:
                    print("\nLast batch all raised Exceptions!")
                    print("Cancelling the rest of the tasks...")
                    for t in pending_tasks:
                        t.cancel()
            elapsed = time.monotonic() - start
            avg_rate = total / elapsed
            print(f"\n  {elapsed:.2f} seconds since start, average of {avg_rate:.2f} regions/s")
            tasks = pending_tasks
            if elapsed >= duration:
                AbortRequested.set()
            if not AbortRequested.is_set():
                if (2 * len(tasks)) < BATCH_SIZE:
                    async for coord in Progress.abatch(BATCH_SIZE):
                        tasks.add(make_task(coord))


def main(mapdir: Path, duration: int, no_auto_reset: bool):
    global Progress, SaverQueue, SaveSuccessQueue

    if duration < 1:
        duration = math.inf

    progress_file = mapdir / PROG_NAME
    Progress = RetrieverProgress(progress_file, auto_reset=(not no_auto_reset))
    if Progress.to_dispatch:
        print(f"{len(Progress.to_dispatch)} jobs still outstanding from last session")

    print("Starting saver worker...", end="", flush=True)
    SaverQueue = MP.Queue()
    SaveSuccessQueue = MP.Queue()
    saver_worker = MP.Process(target=saver, args=(mapdir, SaverQueue, SaveSuccessQueue))
    saver_worker.start()
    print("started.\nDispatching async fetchers!", flush=True)
    asyncio.run(async_main(duration))
    SaverQueue.put(None)
    try:
        print("Flushing SaveSuccess queue ... ", end="", flush=True)
        while True:
            fini = SaveSuccessQueue.get(timeout=5)
            if fini is None:
                break
            Progress.retire(fini)
    except queue.Empty:
        pass
    finally:
        print("flushed")
        Progress.save()
    print("Waiting for saver worker to join ... ", end="", flush=True)
    saver_worker.join()
    print("joined", flush=True)
    print(f"{Progress.outstanding_count:_} outstanding jobs left.")


if __name__ == "__main__":
    opts = options()

    opts.mapdir.mkdir(parents=True, exist_ok=True)

    lockf: Path = opts.mapdir / LOCK_NAME

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

    orig_sigint = signal.getsignal(signal.SIGINT)
    try:
        signal.signal(signal.SIGINT, sigint)
        main(**vars(opts))
        if AbortRequested.is_set():
            print("\nAborted by user.")
    finally:
        signal.signal(signal.SIGINT, orig_sigint)

    lockf.unlink(missing_ok=True)
