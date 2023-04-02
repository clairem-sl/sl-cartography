# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations


import argparse
import asyncio
import itertools
import pickle
import time

import httpx

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, TypedDict

from sl_maptools import MapCoord
from sl_maptools.cap_fetcher import BoundedNameFetcher, CookedTile
# from sl_maptools.bb_fetcher import BoundedNameFetcher, CookedTile


MIN_X = 0
MAX_X = 2100

CONN_LIMIT = 40
SEMA_SIZE = 200
HTTP2 = False
# CONN_LIMIT = 20
# SEMA_SIZE = 100
# HTTP2 = True

BATCH_WAIT = 5

DEFA_DB_DIR = Path("C:\\Cache\\SL-Carto\\")
DB_NAME = "RegionsDB.pkl"
OJ_NAME = "RegionsOJ.pkl"
SJ_NAME = "RegionsSJ.pkl"
LP_NAME = "RegionsLP.pkl"


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


class RegionsDB(FileBackedData):

    def __init__(self, backing_file: Path):
        super().__init__(backing_file, dict)
        self._data: dict[str, RegionsDBRecord] = {}
        self.load()

    def __getitem__(self, item):
        return self._data[item]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, other):
        self._data.update(other)

    def __setitem__(self, key, value):
        self._data[key] = value

    def __len__(self):
        return len(self._data)

    def __contains__(self, item):
        return item in self._data


class JobsSet(FileBackedData):

    def __init__(self, backing_file: Path):
        super().__init__(backing_file, set)
        self._data: set[tuple[int, int]] = set()
        self.load()

    def add(self, item):
        self._data.add(item)

    def remove(self, item):
        self._data.remove(item)

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
    parser = argparse.ArgumentParser("RegionRecorder")

    parser.add_argument("--fromlast", type=int, default=-1)

    parser.add_argument("--miny", type=int, default=-1)
    parser.add_argument("--maxy", type=int, default=-1)

    parser.add_argument("--dbdir", type=Path, default=DEFA_DB_DIR)

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

    OutstandingJobs.remove(xy)
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
            }
        assert isinstance(dbxy, dict)
        record_history()

    if xy in DataBase:
        DataBase[xy].update(dbxy)
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
            if not ignoreseen and (coord not in SeenJobs)
        )
        OutstandingJobs.save()

        tot_jobs = len(OutstandingJobs)
        print(f"{tot_jobs} jobs queued!")

        tasks = [
            asyncio.create_task(fetcher.async_fetch(MapCoord(x, y)), name=f"fetch-{x},{y}")
            for x, y in OutstandingJobs
        ]
        if not tasks:
            print("No unseen jobs, exiting immediately!")
            return

        start = time.monotonic()
        total = 0
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task] = {tasks[0]}  # Dummy, just to enable us to enter the loop
        while pending_tasks:
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
            avg = total/elapsed
            print(f"  {elapsed:.2f} seconds since start, average of {avg:.2f} regions/s")
            if avg > 0:
                eta = datetime.now() + timedelta(seconds=(len(OutstandingJobs) / avg))
                print(f"    ETA: {eta.strftime('%H:%M:%S')}")
            tasks = pending_tasks


def main(miny: int, maxy: int, dbdir: Path, fromlast: int, ignoreseen: bool):
    global DataBase, OutstandingJobs, SeenJobs, SessionParams

    DataBase = RegionsDB(dbdir / DB_NAME)
    orig_len = len(DataBase)
    print(f"{orig_len} records on start.")

    OutstandingJobs = JobsSet(dbdir / OJ_NAME)
    print(f"{len(OutstandingJobs)} jobs still outstanding")

    SeenJobs = JobsSet(dbdir / SJ_NAME)

    SessionParams = WorkParams(dbdir / LP_NAME)
    print(f"{fromlast=} {maxy=} {miny=}")
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

    asyncio.run(async_main(ignoreseen))

    # pprint(DataBase)
    print(f"{len(DataBase)} records now in DataBase (originally {orig_len} records)")
    print(f"DataBase written to {dbdir / DB_NAME}")

    print(f"Job done for Y = [{miny}, {maxy}]")


if __name__ == "__main__":
    main(**vars(options()))
