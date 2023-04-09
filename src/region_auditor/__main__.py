# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import itertools
import pickle
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast, Callable, Final, TypedDict

import httpx

from sl_maptools import MapCoord
from sl_maptools.cap_fetcher import BoundedNameFetcher, CookedTile

# from sl_maptools.bb_fetcher import BoundedNameFetcher, CookedTile


MIN_X: Final[int] = 0
MAX_X: Final[int] = 2100

CONN_LIMIT: Final[int] = 40
SEMA_SIZE: Final[int] = 200
HTTP2: Final[bool] = False
# CONN_LIMIT = 20
# SEMA_SIZE = 100
# HTTP2 = True

BATCH_SIZE: Final[int] = 2000
BATCH_WAIT: Final[float] = 5.0

DEFA_DB_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\")
DB_NAME: Final[str] = "RegionsDB.pkl"
OJ_NAME: Final[str] = "RegionsOJ.pkl"
SJ_NAME: Final[str] = "RegionsSJ.pkl"
LP_NAME: Final[str] = "RegionsLP.pkl"


class FileBackedData:
    def __init__(self, backing_file: Path, default_factory: Callable):
        self.fp = backing_file
        self._factory = default_factory
        self._data = None

    def load(self):
        if self.fp.exists():
            with self.fp.open("rb") as fin:
                self._data = pickle.load(fin)
        else:
            self._data = self._factory()

    def save(self):
        with self.fp.open("wb") as fout:
            pickle.dump(self._data, fout, protocol=pickle.HIGHEST_PROTOCOL)


class RegionsDBRecord(TypedDict):
    first_seen: str
    last_seen: str
    last_check: str
    current_name: str
    name_history: dict[str, list[str]]
    sources: set[str]


class RegionsDB(FileBackedData):
    def __init__(self, backing_file: Path):
        super().__init__(backing_file, dict)
        self._data: dict[str, RegionsDBRecord] = {}
        self.load()

    def __getitem__(self, item) -> RegionsDBRecord:
        return self._data[item]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, other: dict | RegionsDBRecord):
        self._data.update(other)

    def __setitem__(self, key, value):
        self._data[key] = value

    def __len__(self):
        return len(self._data)

    def __contains__(self, item):
        return item in self._data

    def items(self):
        return self._data.items()


class JobsSet(FileBackedData):
    def __init__(self, backing_file: Path):
        super().__init__(backing_file, set)
        self._data: set[tuple[int, int]] = set()
        self.load()

    def add(self, item):
        self._data.add(item)

    def remove(self, item):
        self._data.remove(item)

    def discard(self, element):
        self._data.discard(element)

    def update(self, iterable):
        self._data.update(iterable)

    def clear(self):
        self._data.clear()

    def __len__(self):
        return len(self._data)

    def __contains__(self, item):
        return item in self._data

    def __iter__(self):
        return self._data.__iter__()


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
SeenJobs: JobsSet
SessionParams: WorkParams


def options():
    parser = argparse.ArgumentParser("RegionRecorder", epilog="Use EITHER --fromlast XOR ( --miny AND --maxy )")

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

    parser.add_argument("--ignoreseen", action="store_true", default=False)

    opts = parser.parse_args()

    return opts


def process(tile: CookedTile):
    global DataBase, OutstandingJobs, SeenJobs

    ts = datetime.now().astimezone().isoformat(timespec="minutes")
    xy = tuple(tile.coord)
    dbxy: RegionsDBRecord = DataBase.get(xy)

    def record_history():
        nonlocal dbxy
        seen_name = "" if tile.result is None else tile.result
        prev_name = dbxy["current_name"]
        dbxy["current_name"] = seen_name
        dbxy["last_check"] = ts
        if seen_name:
            dbxy["last_seen"] = ts
        history: dict[str, list[str]] = dbxy["name_history"]
        if seen_name not in history:
            history[seen_name] = [ts]
            return
        if seen_name != prev_name:
            history[seen_name].append(ts)
        else:
            history[seen_name][-1] = ts

    OutstandingJobs.discard(xy)
    SeenJobs.add(xy)

    if tile.result is None:
        if dbxy is None:
            return
        assert isinstance(dbxy, dict)
        record_history()
    else:
        assert isinstance(tile.result, str)
        if dbxy is None:
            dbxy: RegionsDBRecord = {
                "first_seen": ts,
                "last_seen": "",
                "last_check": "",
                "current_name": "",
                "name_history": {},
                "sources": {"cap"},
            }
        assert isinstance(dbxy, dict)
        record_history()

    if xy in DataBase:
        DataBase[xy].update(cast(dict, dbxy))
    else:
        DataBase[xy] = dbxy


async def async_main(ignoreseen: bool):
    global OutstandingJobs, SeenJobs, SessionParams
    miny = SessionParams.miny
    maxy = SessionParams.maxy

    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(SEMA_SIZE, client, cooked=True)
        # coords = [MapCoord(x, y) for x in range(950, 1050) for y in range(950, 1050)]

        OutstandingJobs.update(
            coord
            for coord in itertools.product(range(MIN_X, MAX_X + 1), range(miny, maxy + 1))
            if ignoreseen or (coord not in SeenJobs)
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

        tasks: set[asyncio.Task] = set()
        async for coord in batch(BATCH_SIZE):
            tasks.add(asyncio.create_task(fetcher.async_fetch(MapCoord(*coord))))

        if not tasks:
            print("No unseen jobs, exiting immediately!")
            return

        start = time.monotonic()
        total = 0
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task | None] = {None}  # Dummy, just to enable us to enter the loop
        while pending_tasks:
            print(f"{len(tasks)} async jobs =>", end=" ")
            done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
            total += len(done)
            c = e = 0
            for c, fut in enumerate(done, start=1):
                if exc := fut.exception():
                    e += 1
                    print(f"\n{fut.get_name()} raised Exception: <{type(exc)}> {exc}")
                    continue
                rslt: CookedTile = fut.result()
                process(rslt)
                if rslt.result:
                    if rslt.result.isdigit():
                        print(f"\n{rslt}")
                    else:
                        print(f"{rslt}", end=" ", flush=True)
            if c:
                DataBase.save()
                OutstandingJobs.save()
                SeenJobs.save()
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
            avg = total / elapsed
            print(f"  {elapsed:.2f} seconds since start, average of {avg:.2f} regions/s")
            if avg > 0:
                eta = datetime.now() + timedelta(seconds=(len(OutstandingJobs) / avg))
                print(f"    ETA: {eta.strftime('%H:%M:%S')}")
            tasks = pending_tasks
            if (2 * len(tasks)) < BATCH_SIZE:
                async for coord in batch(BATCH_SIZE):
                    tasks.add(asyncio.create_task(fetcher.async_fetch(MapCoord(*coord))))


def main(miny: int, maxy: int, dbdir: Path, fromlast: int, ignoreseen: bool):
    global DataBase, OutstandingJobs, SeenJobs, SessionParams

    if fromlast == -1:
        if miny == maxy == -1:
            print("Must specify EITHER --fromlast XOR (--miny AND --maxy)", file=sys.stderr)
            sys.exit(1)
        elif miny == -1 or maxy == -1:
            print("Must specify BOTH --miny AND --maxy", file=sys.stderr)
            sys.exit(1)
    else:
        if miny != -1 or maxy != -1:
            print("If using --fromlast, NEITHER --miny NOR --maxy may be specified", file=sys.stderr)
            sys.exit(1)

    DataBase = RegionsDB(dbdir / DB_NAME)
    orig_len = len(DataBase)
    print(f"{orig_len} records on start.")
    for k, v in DataBase.items():
        if "sources" not in v:
            v["sources"] = {"cap"}

    OutstandingJobs = JobsSet(dbdir / OJ_NAME)
    print(f"{len(OutstandingJobs)} jobs still outstanding")

    SeenJobs = JobsSet(dbdir / SJ_NAME)

    SessionParams = WorkParams(dbdir / LP_NAME)
    if fromlast != -1:
        maxy = SessionParams.miny
        miny = maxy - fromlast
        if miny < 0:
            miny = 0
            if maxy <= miny:
                maxy = 2100
                miny = 2100 - fromlast
                SeenJobs.clear()
    SessionParams.maxy = maxy
    SessionParams.miny = miny
    SessionParams.save()

    print(f"Getting region names from range [{maxy}, {miny}]")
    start = time.monotonic()
    asyncio.run(async_main(ignoreseen))
    elapsed = time.monotonic() - start

    # pprint(DataBase)
    print(f"{len(DataBase)} records now in DataBase (originally {orig_len} records)")
    print(f"DataBase written to {dbdir / DB_NAME}")

    print(f"Job done for Y = [{miny}, {maxy}] in {elapsed:_.2f} seconds")


if __name__ == "__main__":
    main(**vars(options()))
