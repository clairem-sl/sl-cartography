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
import multiprocessing.synchronize as MPSync
# import pickle
import queue
import re
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, TypedDict, cast, Protocol

import httpx
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

from retriever import RetrieverProgress
from sl_maptools import MapCoord
from sl_maptools.fetchers import RawResult
# from sl_maptools.image_processing import calculate_dominant_colors, FASCIA_COORDS, RGBTuple
from sl_maptools.fetchers.map import BoundedMapFetcher


RE_MAPFILENAME: re.Pattern = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_(?P<ts>[0-9-]+)\.jpg$")

SSIM_THRESHOLD: Final[float] = 0.98
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
TriggerCondition: MPSync.Condition
EndingEvent: MPSync.Event
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


# def save_domc(
#     mapdir: Path,
#     trigger_condition: MPSync.Condition,
#     ending_event: MPSync.Event,
#     dominant_colors: None | dict[tuple[int, int], dict[int, list[RGBTuple]]],
# ):
#     signal.signal(signal.SIGINT, signal.SIG_IGN)
#     if dominant_colors is None:
#         return
#
#     def deeply_equal(d1: dict, d2: dict):
#         if len(d1) != len(d2):
#             return False
#         if sorted(d1.keys()) != sorted(d2.keys()):
#             return False
#         for k, v1 in d1.items():
#             v2 = d2[k]
#             if type(v1) != type(v2):
#                 return False
#             if isinstance(v1, dict):
#                 if not deeply_equal(v1, v2):
#                     return False
#             else:
#                 if v1 != v2:
#                     return False
#         return True
#
#     domc_pkl_path = mapdir / DOMC_NAME
#     # Make a copy first, so we can detect changes later.
#     domc = dominant_colors.copy()
#     while not ending_event.is_set():
#         trigger_condition.acquire()
#         trigger_condition.wait()
#
#         # Copy dominant_colors, which is a manager.dict(), so that when we process it there won't be any changes
#         curr_domc = dominant_colors.copy()
#         if deeply_equal(domc, curr_domc):
#             continue
#
#         domc = curr_domc
#         with domc_pkl_path.open("wb") as fout:
#             pickle.dump(domc, fout, protocol=pickle.HIGHEST_PROTOCOL)
#         print(f"⏬[{len(domc)}]", end="", flush=True)


def saver(
    mapdir: Path,
    mapfilesets: dict[tuple[int, int], list[Path]],
    save_queue: MP.Queue,
    success_queue: MP.Queue,
    # dominant_colors: None | dict[tuple[int, int], dict[int, list[RGBTuple]]],
):
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
        coord: MapCoord = regmap["coord"]
        shm: MPSharedMem.SharedMemory = regmap["shm"]
        blob = cast(bytes, shm.buf)
        try:
            try:
                tsf = regmap["tsf"]
                targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
                with targf.open("wb") as fout:
                    fout.write(blob)
                print("💾", end="", flush=True)
            except Exception:
                raise

            with io.BytesIO(blob) as bio:
                img: Image.Image = Image.open(bio)
                img.load()

            # if dominant_colors is not None:
            #     domc: dict[int, list[RGBTuple]] = {}
            #     for fasz in FASCIA_COORDS:
            #         domc[fasz] = calculate_dominant_colors(img, fasz)
            #     dominant_colors[tuple(coord)] = domc

            # Prune older file of same coordinate if really similar
            if not (coordfiles := mapfilesets.get(coord, [])):
                continue
            f2 = coordfiles[-1]
            # noinspection PyTypeChecker
            f1_arr = np.asarray(img.convert("L"))
            try:
                with f2.open("rb") as fin:
                    f2_img = Image.open(fin)
                    f2_img.load()
                # noinspection PyTypeChecker
                f2_arr = np.asarray(f2_img.convert("L"))
                # Image similarity test using Structural Similarity Index,
                # see https://pyimagesearch.com/2014/09/15/python-compare-two-images/
                if ssim(f1_arr, f2_arr) > SSIM_THRESHOLD:
                    f2.unlink()
                    coordfiles.pop()
                    print("❌", end="", flush=True)
            except FileNotFoundError:
                coordfiles.pop()
            coordfiles.append(targf)
            mapfilesets[coord] = coordfiles

            success_queue.put(coord)
        finally:
            shm.close()


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
            except queue.Empty:
                pass
            TriggerCondition.acquire()
            TriggerCondition.notify_all()
            TriggerCondition.release()
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
):
    global Progress, SaverQueue, SaveSuccessQueue, TriggerCondition, EndingEvent

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
    if Progress.to_dispatch:
        print(f"{len(Progress.to_dispatch)} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")
        if Progress.max_unprocessed_y < 0:
            print("No rows left to process.")
            print(f"Delete the file {progress_file} to reset. (Or specify --auto-reset)")

    with MP.Manager() as manager, MPMgr.SharedMemoryManager() as shm_manager:
        print("Starting saver worker...", end="", flush=True)
        SaverQueue = MP.Queue()
        SaveSuccessQueue = MP.Queue()

        # dominant_colors: None | dict[tuple[int, int], dict[int, list[RGBTuple]]]
        # if nodom:
        #     dominant_colors = None
        # else:
        #     domc_pkl_path = mapdir / DOMC_NAME
        #     if not domc_pkl_path.exists():
        #         with domc_pkl_path.open("wb") as fout:
        #             pickle.dump({}, fout, protocol=pickle.HIGHEST_PROTOCOL)
        #         dominant_colors = manager.dict()
        #     else:
        #         with domc_pkl_path.open("rb") as fin:
        #             dominant_colors = manager.dict(pickle.load(fin))

        _mapfilesets: dict[tuple[int, int], list[Path]] = {}
        m: re.Match
        flist: list[Path]
        for mapfile in sorted(mapdir.glob("*.jpg")):
            if (m := RE_MAPFILENAME.match(mapfile.name)) is None:
                continue
            coord = (int(m.group("x")), int(m.group("y")))
            _mapfilesets.setdefault(coord, []).append(mapfile)
        mapfilesets = manager.dict(_mapfilesets)

        # saver_args = (mapdir, mapfilesets, SaverQueue, SaveSuccessQueue, dominant_colors)
        saver_args = (mapdir, mapfilesets, SaverQueue, SaveSuccessQueue)
        #
        TriggerCondition = manager.Condition()
        EndingEvent = manager.Event()
        EndingEvent.clear()
        # save_domc_args = (mapdir, TriggerCondition, EndingEvent, dominant_colors)
        #
        pool: MPPool.Pool
        # with MP.Pool(workers, saver, saver_args) as pool, MP.Pool(1, save_domc, save_domc_args) as pool2:
        with MP.Pool(workers, saver, saver_args) as pool:

            print("started.\nDispatching async fetchers!", flush=True)
            try:
                signal.signal(signal.SIGINT, sigint_handler)
                asyncio.run(async_main(dur, shm_manager))
            finally:
                signal.signal(signal.SIGINT, OrigSigINT)

            for _ in range(workers):
                SaverQueue.put(None)
            print("\nClosing worker pool ... ", end="", flush=True)
            pool.close()
            pool.join()
            SaverQueue.close()
            SaverQueue.join_thread()
            print("closed")
            try:
                print("Flushing SaveSuccess queue ... ", end="", flush=True)
                while True:
                    fini_coord = SaveSuccessQueue.get(timeout=5)
                    SharedMemoryAllocations[fini_coord].close()
                    Progress.retire(fini_coord)
            except queue.Empty:
                pass
            finally:
                print("flushed")
                Progress.save()
            # print("Send signal to save_domc to finish ... ", end="", flush=True)
            # pool2.close()
            # EndingEvent.set()
            # TriggerCondition.acquire()
            # TriggerCondition.notify_all()
            # TriggerCondition.release()
            # print("sent", end=" ", flush=True)
            # pool2.join()
            # print("joined", flush=True)
    print(f"{Progress.outstanding_count:_} outstanding jobs left.")


if __name__ == "__main__":
    opts = options()

    opts.mapdir.mkdir(parents=True, exist_ok=True)

    lockf: Path = opts.mapdir / LOCK_NAME
    if not opts.force:
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

    main(**vars(opts))
    if AbortRequested.is_set():
        print("\nAborted by user.")

    lockf.unlink(missing_ok=True)
