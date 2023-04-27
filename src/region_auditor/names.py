# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import itertools
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, TypedDict, cast

import httpx

from region_auditor import FileBackedData, JobsSet
from region_auditor.xchg.exportDB import export
from sl_maptools import MapCoord
from sl_maptools.fetchers.cap import BoundedNameFetcher, CookedResult

# from sl_maptools.bb_fetcher import BoundedNameFetcher, CookedTile


MIN_X: Final[int] = 0
MAX_X: Final[int] = 2100

CONN_LIMIT: Final[int] = 40
SEMA_SIZE: Final[int] = 200
HTTP2: Final[bool] = False
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
DB_NAME: Final[str] = "RegionsDB.pkl"
OJ_NAME: Final[str] = "RegionsOJ.pkl"
LP_NAME: Final[str] = "RegionsLP.pkl"
LOCK_NAME: Final[str] = "RegionsDB.lock"


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

    parser.add_argument(
        "--no-export",
        action="store_true",
        default=False,
        help="If specified, don't export DB as YAML",
    )

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


def process(tile: CookedResult):
    global DataBase, OutstandingJobs

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


async def async_main():
    global OutstandingJobs, SessionParams
    miny = SessionParams.miny
    maxy = SessionParams.maxy

    limits = httpx.Limits(
        max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT
    )
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(SEMA_SIZE, client, cooked=True)
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
                rslt: CookedResult = fut.result()
                process(rslt)
                if rslt.result:
                    if rslt.result.isdigit():
                        print(
                            f"\n({rslt.coord.x},{rslt.coord.y}){rslt.result}",
                            end="? ",
                            flush=True,
                        )
                    else:
                        print(f"{rslt}", end=" ", flush=True)
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


def main(miny: int, maxy: int, dbdir: Path, fromlast: int, no_export: bool):
    global DataBase, OutstandingJobs, SessionParams

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
    for k, v in DataBase.items():
        if "sources" not in v:
            v["sources"] = {"cap"}

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

    print(f"Getting region names from range [{maxy}, {miny}]")
    start = time.monotonic()
    asyncio.run(async_main())
    elapsed = time.monotonic() - start

    # pprint(DataBase)
    print(f"{len(DataBase)} records now in DataBase (originally {orig_len} records)")
    print(f"DataBase written to {dbdir / DB_NAME}")

    print(f"Job done for Y = [{miny}, {maxy}] in {elapsed:_.2f} seconds")
    print(f"  {len(OutstandingJobs)} outstanding jobs left.")

    if not no_export:
        print("Exporting DB ... ", end="")
        print(str(export(dbdir / DB_NAME, quiet=True)))


if __name__ == "__main__":
    opts = options()

    lockf: Path = opts.dbdir / LOCK_NAME
    try:
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
    finally:
        lockf.unlink(missing_ok=True)
