# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations


# Logic
#
# For each coordinate
# If region does not exist
#   If item exists
#     Record history
#     current_name = seen_name
# If region exists
#   If item not exists
#     Create item:
#       first_seen = ts
#   last_seen = ts
#   Record history
#   current_name = seen_name
#
# Record history (seen_name, current_name)
#   If seen_name not in history
#     Create history, with empty list
#     Append ts
#     Return
#   if seen_name == current_name
#     REPLACE last entry of item with ts
#   else
#     Append ts


import asyncio
import pickle
import time

import httpx

from datetime import datetime
from pathlib import Path
from pprint import pprint
from typing import Any

from sl_maptools import MapCoord
from sl_maptools.cap_fetcher import BoundedNameFetcher, CookedTile
# from sl_maptools.bb_fetcher import BoundedNameFetcher, CookedTile


CONN_LIMIT = 40
SEMA_SIZE = 200
HTTP2 = False
# CONN_LIMIT = 20
# SEMA_SIZE = 100
# HTTP2 = True

BATCH_WAIT = 5

DB_FILEPATH = Path(r"C:\Cache\SL-Carto\RegionsDB.pkl")


DataBase: dict[tuple[int, int], dict] = {}


def process(tile: CookedTile):
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


async def async_main():
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(SEMA_SIZE, client, cooked=True)
        tasks = []
        # coords = [MapCoord(x, y) for x in range(950, 1050) for y in range(950, 1050)]
        coords = [MapCoord(x, y) for x in range(0, 2100) for y in range(2000, 2100)]
        tot_jobs = len(coords)
        print(f"{tot_jobs} jobs queued!")
        for c in coords:
            tasks.append(asyncio.create_task(fetcher.async_fetch(c), name=f"fetch-{c}"))
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
            print(
                f"\n{c} results in last batch ----- "
                f"{100*total/tot_jobs:.2f}% completed, "
                f"{len(DataBase)} regions seen/known so far"
            )
            elapsed = time.monotonic() - start
            print(f"  {elapsed:.2f} seconds since start, average of {total/elapsed:.2f} regions/s")
            tasks = pending_tasks


def main():
    global DataBase
    if DB_FILEPATH.exists():
        with DB_FILEPATH.open("rb") as fin:
            DataBase = pickle.load(fin)
    else:
        DataBase = {}
    print(f"{len(DataBase)} records so far.")
    asyncio.run(async_main())
    pprint(DataBase)
    with DB_FILEPATH.open("wb") as fout:
        pickle.dump(DataBase, fout, pickle.HIGHEST_PROTOCOL)
    print(f"DataBase written to {DB_FILEPATH}")


if __name__ == "__main__":
    main()
