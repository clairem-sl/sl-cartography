# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import itertools
import multiprocessing as MP
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, TypedDict, cast

import httpx
from PIL import Image

from region_auditor import FileBackedData, JobsSet
from sl_maptools import MapCoord, MapRegion
from sl_maptools.fetchers.map import BoundedMapFetcher

# from sl_maptools.bb_fetcher import BoundedNameFetcher, CookedTile


MIN_X: Final[int] = 0
MAX_X: Final[int] = 2100

CONN_LIMIT: Final[int] = 20
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

DEFA_DB_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\")
DEFA_MAPS_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\Maps\\")
DB_NAME: Final[str] = "MapsDB.pkl"
OJ_NAME: Final[str] = "MapsOJ.pkl"
LP_NAME: Final[str] = "MapsLP.pkl"
LOCK_NAME: Final[str] = "MapsDB.lock"


class MapsDBRecord(TypedDict):
    first_seen: str
    last_seen: str
    last_check: str


class RegionsDB(FileBackedData):
    def __init__(self, backing_file: Path):
        super().__init__(backing_file, dict)
        self._data: dict[str, MapsDBRecord] = {}
        self.load()

    def __getitem__(self, item) -> MapsDBRecord:
        return self._data[item]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, other: dict | MapsDBRecord):
        self._data.update(other)

    def __setitem__(self, key, value):
        self._data[key] = value

    def __len__(self):
        return len(self._data)

    def __contains__(self, item):
        return item in self._data

    def items(self):
        return self._data.items()


class WorkParamsDict(TypedDict):
    miny: int
    maxy: int


class WorkParams(FileBackedData):
    def __init__(self, backing_file: Path):
        self._data: WorkParamsDict
        super().__init__(backing_file, WorkParamsDict)
        self.load()
        self._data.setdefault("miny", -1)
        self._data.setdefault("maxy", -1)

    @property
    def miny(self) -> int:
        return self._data["miny"]

    @miny.setter
    def miny(self, value: int):
        self._data["miny"] = value

    @property
    def maxy(self) -> int:
        return self._data["maxy"]

    @maxy.setter
    def maxy(self, value: int):
        self._data["maxy"] = value


DataBase: RegionsDB
OutstandingJobs: JobsSet
SessionParams: WorkParams
SaverQueue: MP.Queue


def options():
    parser = argparse.ArgumentParser(
        "region_auditor", epilog="Use EITHER --fromlast XOR ( --miny AND --maxy )"
    )

    group = parser.add_argument_group("Automatic Range (based on last scanned range)")
    group.add_argument(
        "--fromlast",
        metavar="ROWS",
        type=int,
        default=-1,
        help="How many rows to continue from the previous session. If row wraps, will start from 2100 down.",
    )

    group = parser.add_argument_group("Explicit Range")
    group.add_argument("--miny", metavar="NUM", type=int, default=-1)
    group.add_argument("--maxy", metavar="NUM", type=int, default=-1)

    parser.add_argument("--dbdir", metavar="DIR", type=Path, default=DEFA_DB_DIR)
    parser.add_argument("--mapdir", metavar="DIR", type=Path, default=DEFA_MAPS_DIR)

    # parser.add_argument(
    #     "--source",
    #     nargs="*",
    #     choices=VALID_SOURCES,
    #     help=(
    #         f"Space-separated source to use for audit. "
    #         f"Valid values are one or more combination from {VALID_SOURCES}"
    #     ),
    # )

    _opts = parser.parse_args()

    return _opts


class QJob(TypedDict):
    coord: MapCoord
    tsf: str
    image: Image.Image


def saver(mapdir: Path, queue: MP.Queue):
    while True:
        if queue.empty():
            time.sleep(1)
            continue
        item = queue.get()
        if item is None:
            break
        regmap: QJob = cast(QJob, item)
        coord = regmap["coord"]
        tsf = regmap["tsf"]
        targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
        regmap["image"].save(targf)
        print("💾", end="")


def process(tile: MapRegion, mapdir: Path):
    global DataBase, OutstandingJobs

    nao = datetime.now()
    ts = nao.astimezone().isoformat(timespec="minutes")
    tsf = datetime.strftime(nao, "%y%m%d-%H%M")
    xy = tuple(tile.coord)
    dbxy: MapsDBRecord = DataBase.get(xy)

    OutstandingJobs.discard(xy)

    if dbxy is None:
        if tile.image is None:
            return
        dbxy = {
            "first_seen": ts,
            "last_seen": "",
            "last_check": "",
        }
    dbxy["last_check"] = ts

    if tile.image is not None:
        assert isinstance(tile.image, Image.Image)
        # targf = mapdir / f"{tile.coord.x}-{tile.coord.y}_{tsf}.jpg"
        # tile.image.save(targf)
        SaverQueue.put({
            "coord": tile.coord,
            "tsf": tsf,
            "image": tile.image,
        })
        dbxy["last_seen"] = ts

    if xy in DataBase:
        DataBase[xy].update(cast(dict, dbxy))
    else:
        DataBase[xy] = dbxy


async def async_main(mapdir: Path):
    global OutstandingJobs, SessionParams
    miny = SessionParams.miny
    maxy = SessionParams.maxy

    limits = httpx.Limits(
        max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT
    )
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(SEMA_SIZE, client, cooked=True)
        # coords = [MapCoord(x, y) for x in range(950, 1050) for y in range(950, 1050)]

        OutstandingJobs.update(
            coord
            for coord in itertools.product(
                range(MIN_X, MAX_X + 1), range(miny, maxy + 1)
            )
        )
        OutstandingJobs.save()

        tot_jobs = len(OutstandingJobs)
        print(f"{tot_jobs} jobs to do in this session!")

        undispatched_jobs: set[tuple[int, int]] = {r for r in OutstandingJobs}

        async def batch(size: int):
            for _ in range(size):
                if not undispatched_jobs:
                    return
                yield undispatched_jobs.pop()

        def make_task(coord: tuple[int, int]):
            return asyncio.create_task(
                fetcher.async_fetch(MapCoord(*coord)), name=str(coord)
            )

        tasks: set[asyncio.Task] = {
            make_task(coord) async for coord in batch(BATCH_SIZE)
        }
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
                process(rslt, mapdir)
                if rslt.image:
                    print(f"({rslt.coord.x},{rslt.coord.y})✔", end=" ")
            if c:
                DataBase.save()
                OutstandingJobs.save()
                if e == c:
                    print("\nLast batch all raised Exceptions!")
                    print("Cancelling the rest of the tasks...")
                    for t in pending_tasks:
                        t.cancel()
            print(
                f"\n{c} results in last batch ----- "
                f"{100*total/tot_jobs:.2f}% completed, "
                f"{len(DataBase)} regions seen/known so far"
            )
            elapsed = time.monotonic() - start
            avg_rate = total / elapsed
            print(
                f"  {elapsed:.2f} seconds since start, average of {avg_rate:.2f} regions/s"
            )
            if avg_rate > 0:
                eta = datetime.now() + timedelta(
                    seconds=(len(OutstandingJobs) / avg_rate)
                )
                print(f"    ETA: {eta.strftime('%H:%M:%S')}")
            tasks = pending_tasks
            if (2 * len(tasks)) < BATCH_SIZE:
                async for coord in batch(BATCH_SIZE):
                    tasks.add(make_task(coord))


def main(
    miny: int, maxy: int, dbdir: Path, mapdir: Path, fromlast: int
):
    global DataBase, OutstandingJobs, SessionParams, SaverQueue

    if fromlast == -1:
        if miny == maxy == -1:
            print(
                "Must specify EITHER --fromlast XOR (--miny AND --maxy)",
                file=sys.stderr,
            )
            sys.exit(1)
        elif miny == -1 or maxy == -1:
            print("Must specify BOTH --miny AND --maxy", file=sys.stderr)
            sys.exit(1)
    else:
        if miny != -1 or maxy != -1:
            print(
                "If using --fromlast, NEITHER --miny NOR --maxy may be specified",
                file=sys.stderr,
            )
            sys.exit(1)

    DataBase = RegionsDB(dbdir / DB_NAME)
    orig_len = len(DataBase)
    print(f"{orig_len} records on start.")

    OutstandingJobs = JobsSet(dbdir / OJ_NAME)
    print(f"{len(OutstandingJobs)} jobs still outstanding")

    SessionParams = WorkParams(dbdir / LP_NAME)
    if fromlast != -1:
        maxy = SessionParams.miny
        miny = maxy - fromlast
        if miny < 0:
            miny = 0
            if maxy <= miny:
                maxy = 2100
                miny = 2100 - fromlast
    SessionParams.maxy = maxy
    SessionParams.miny = miny
    SessionParams.save()

    print(f"Getting maps from range [{maxy}, {miny}]")
    mapdir.mkdir(parents=True, exist_ok=True)
    SaverQueue = MP.Queue()
    saver_worker = MP.Process(target=saver, args=(mapdir, SaverQueue))
    saver_worker.start()
    start = time.monotonic()
    asyncio.run(async_main(mapdir))
    SaverQueue.put(None)
    print("Waiting for saver worker to join...", end="")
    saver_worker.join()
    elapsed = time.monotonic() - start

    # pprint(DataBase)
    print(f"{len(DataBase)} records now in DataBase (originally {orig_len} records)")
    print(f"DataBase written to {dbdir / DB_NAME}")

    print(f"Job done for Y = [{miny}, {maxy}] in {elapsed:_.2f} seconds")
    print(f"  {len(OutstandingJobs)} outstanding jobs left.")


if __name__ == "__main__":
    opts = options()

    lockf: Path = opts.dbdir / LOCK_NAME
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
    try:
        main(**vars(opts))
    except KeyboardInterrupt:
        print("\nAborted by user.")
    lockf.unlink(missing_ok=True)
