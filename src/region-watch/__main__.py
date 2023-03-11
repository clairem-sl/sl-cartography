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
from typing import Any

from sl_maptools import MapCoord
from sl_maptools.cap_fetcher import BoundedNameFetcher, CookedTile
# from sl_maptools.bb_fetcher import BoundedNameFetcher, CookedTile


MIN_Y = 1400
MAX_Y = 1600

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


DataBase: dict[tuple[int, int], dict] = {}
OutstandingJobs: set[tuple[int, int]] = set()
SeenJobs: set[tuple[int, int]] = set()


def options():
    parser = argparse.ArgumentParser("RegionRecorder")

    parser.add_argument("--miny", type=int)
    parser.add_argument("--maxy", type=int)

    parser.add_argument("--dbdir", type=Path, default=DEFA_DB_DIR)

    opts = parser.parse_args()

    return opts


def process(tile: CookedTile):
    global DataBase, OutstandingJobs, SeenJobs

    ts = datetime.now().astimezone().isoformat(timespec="minutes")
    xy = tuple(tile.coord)
    dbxy: dict[str, Any] = DataBase.get(xy)

    def record_history():
        assert isinstance(dbxy, dict)
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
            dbxy = {
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


async def async_main(miny: int, maxy: int, dbdir: Path):
    global OutstandingJobs, SeenJobs

    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(SEMA_SIZE, client, cooked=True)
        # coords = [MapCoord(x, y) for x in range(950, 1050) for y in range(950, 1050)]

        OutstandingJobs.update(
            coord
            for coord in itertools.product(range(MIN_X, MAX_X + 1), range(miny, maxy + 1))
            if coord not in SeenJobs
        )
        with (dbdir / OJ_NAME).open("wb") as fout:
            pickle.dump(OutstandingJobs, fout, pickle.HIGHEST_PROTOCOL)

        tot_jobs = len(OutstandingJobs)
        print(f"{tot_jobs} jobs queued!")

        tasks = [
            asyncio.create_task(fetcher.async_fetch(MapCoord(x, y)), name=f"fetch-{x},{y}")
            for x, y in OutstandingJobs
        ]

        start = time.monotonic()
        total = 0
        pending_tasks = [1]
        while pending_tasks:
            done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
            total += len(done)
            c = 0
            for c, fut in enumerate(done, start=1):
                rslt: CookedTile = fut.result()
                process(rslt)
                if rslt.result:
                    if rslt.result.isdigit():
                        print(f"\n{rslt}")
                    else:
                        print(f"{rslt}", end=" ", flush=True)
            if c:
                with (dbdir / DB_NAME).open("wb") as fout:
                    pickle.dump(DataBase, fout, pickle.HIGHEST_PROTOCOL)
                with (dbdir / OJ_NAME).open("wb") as fout:
                    pickle.dump(OutstandingJobs, fout, pickle.HIGHEST_PROTOCOL)
                with (dbdir / SJ_NAME).open("wb") as fout:
                    pickle.dump(SeenJobs, fout, pickle.HIGHEST_PROTOCOL)
            print(
                f"\n{c} results in last batch ----- "
                f"{100*total/tot_jobs:.2f}% completed, "
                f"{len(DataBase)} regions seen/known so far"
            )
            elapsed = time.monotonic() - start
            avg = total/elapsed
            print(f"  {elapsed:.2f} seconds since start, average of {avg:.2f} regions/s")
            eta = datetime.now() + timedelta(seconds=(len(OutstandingJobs) / avg))
            print(f"    ETA: {eta.strftime('%H:%M:%S')}")
            tasks = pending_tasks


def main(miny: int, maxy: int, dbdir: Path):
    global DataBase, OutstandingJobs, SeenJobs

    if (dbdir / DB_NAME).exists():
        with (dbdir / DB_NAME).open("rb") as fin:
            DataBase = pickle.load(fin)
    else:
        DataBase = {}
    orig_len = len(DataBase)
    print(f"{orig_len} records on start.")

    if (dbdir / OJ_NAME).exists():
        with (dbdir / OJ_NAME).open("rb") as fin:
            OutstandingJobs = pickle.load(fin)
    else:
        OutstandingJobs = set()
    print(f"{len(OutstandingJobs)} jobs still outstanding")

    if (dbdir / SJ_NAME).exists():
        with (dbdir / SJ_NAME).open("rb") as fin:
            SeenJobs = pickle.load(fin)
    else:
        SeenJobs = set()

    asyncio.run(async_main(miny, maxy, dbdir))

    # pprint(DataBase)
    print(f"{len(DataBase)} records now in DataBase (originally {orig_len} records)")
    print(f"DataBase written to {dbdir / DB_NAME}")


if __name__ == "__main__":
    main(**vars(options()))
