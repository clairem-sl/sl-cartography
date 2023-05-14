# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import asyncio
import pickle
import re
from datetime import datetime
from pathlib import Path
from pprint import pprint
from typing import Final, Protocol, TypedDict, cast

import httpx

from retriever_v4 import (
    RetrieverApplication,
    RetrieverProgress,
    TimeOptions,
    add_timeoptions,
    calc_duration,
    dispatch_fetcher,
    handle_sigint,
)
from sl_maptools import CoordType, MapCoord, RegionsDBRecord
from sl_maptools.fetchers import CookedResult
from sl_maptools.fetchers.cap import BoundedNameFetcher
from sl_maptools.utils import ConfigReader

CONN_LIMIT: Final[int] = 80
# SEMA_SIZE: Final[int] = 180
HTTP2: Final[bool] = False
START_BATCH_SIZE: Final[int] = 600
BATCH_WAIT: Final[float] = 5.0
MAVG_SAMPLES: Final[int] = 5
ACCEPTABLE_STATUSCODES: Final[set[int]] = {0, 200, 403}

CONFIG_FILE = Path("config.toml")
Config = ConfigReader(CONFIG_FILE)

Progress: RetrieverProgress

AbortRequested = asyncio.Event()

DataBase: dict[CoordType, RegionsDBRecord] = {}


class ChangeStatsDict(TypedDict):
    new: int
    changed: int
    gone: int
    revived: int
    failure: int


ChangeStats: ChangeStatsDict = {
    "new": 0,
    "changed": 0,
    "gone": 0,
    "revived": 0,
    "failure": 0,
}


RE_HHMM = re.compile(r"^(\d{1,2}):(\d{1,2})$")


class RetrieverNamesOptions(Protocol):
    dbdir: Path
    force: bool
    auto_reset: bool
    min_batch_size: int
    abort_low_rps: int


class OptionsProtocol(RetrieverNamesOptions, TimeOptions, Protocol):
    pass


def get_options() -> OptionsProtocol:
    parser = argparse.ArgumentParser("retriever_v4.names")

    parser.add_argument("--dbdir", type=Path, default=Config.names.dir)
    parser.add_argument("--force", action="store_true")

    parser.add_argument(
        "--auto-reset",
        action="store_true",
        help=(
            f"If specified, retriever will wrap up back to maxrow "
            f"({RetrieverProgress.DEFA_MAX_COORD[1]}) upon finishing row 0"
        ),
    )
    parser.add_argument("--min-batch-size", metavar="N", type=int, default=0, help="Batch size will not go lower than this")
    parser.add_argument("--abort-low-rps", metavar="N", type=int, default=-1, help="If rps drops below this for some time, abort")

    add_timeoptions(parser)

    _opts = parser.parse_args()

    return cast(OptionsProtocol, _opts)


def process(tile: CookedResult) -> bool:
    global DataBase

    ts = datetime.now().astimezone().isoformat(timespec="minutes")
    xy = tile.coord.x, tile.coord.y
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
        if seen_name != prev_name:
            if seen_name:
                if prev_name:
                    ChangeStats["changed"] += 1
                else:
                    ChangeStats["revived"] += 1
            else:
                ChangeStats["gone"] += 1
        if seen_name not in history:
            print("🉑", end="", flush=True)
            history[seen_name] = [ts]
            return
        if seen_name != prev_name:
            print("🉑", end="", flush=True)
            history[seen_name].append(ts)
        else:
            history[seen_name][-1] = ts

    if tile.result is None:
        if dbxy is None:
            return False
        assert isinstance(dbxy, dict)
        record_history()
    else:
        try:
            assert isinstance(tile.result, str)
        except AssertionError:
            print(f"{tile.result=} ({type(tile.result)})")
            print(f"{tile=}")
            raise
        if dbxy is None:
            ChangeStats["new"] += 1
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
    return True


async def amain(db_path: Path, duration: int, min_batch_size: int, abort_low_rps: int):
    limits = httpx.Limits(
        max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT
    )
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(
            CONN_LIMIT * 3, client, cooked=True, cancel_flag=AbortRequested
        )
        shown = False

        def make_task(coord: CoordType):
            return asyncio.create_task(
                fetcher.async_fetch(MapCoord(*coord)), name=str(coord)
            )

        def pre_batch():
            nonlocal shown
            shown = False

        def process_result(fut_result: None | CookedResult) -> bool:
            nonlocal shown
            if fut_result is None:
                return False
            if fut_result.status_code not in ACCEPTABLE_STATUSCODES:
                ChangeStats["failure"] += 1
                return False
            if fut_result.result:
                if not shown:
                    shown = True
                    print("🌐", end="")
                print(
                    f' ({fut_result.coord.x},{fut_result.coord.y})"{fut_result.result}"',
                    end="",
                    flush=True,
                )
            Progress.retire(fut_result.coord)
            return process(fut_result)

        def post_batch():
            if not shown:
                print("Nothing retrieved", end="")
                return
            with db_path.open("wb") as fout:
                pickle.dump(DataBase, fout)

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


def main(app_context: RetrieverApplication, opts: OptionsProtocol):
    global DataBase, Progress

    dur = calc_duration(opts)

    Progress = RetrieverProgress((opts.dbdir / Config.names.progress), auto_reset=opts.auto_reset)
    if Progress.outstanding_count:
        print(f"{Progress.outstanding_count} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")
        if Progress.next_y < 0:
            print("No rows left to process.")
            print(
                f"Delete the file {opts.dbdir / Config.names.progress} to reset. (Or specify --auto-reset)"
            )
            return
    print(f"Next coordinate: {Progress.next_coordinate}")

    db_path = opts.dbdir / Config.names.db
    if db_path.exists():
        with db_path.open("rb") as fin:
            DataBase = pickle.load(fin)
    print(f"DataBase already contains {len(DataBase)} regions.")

    start_coord = Progress.next_coordinate
    #
    print("Dispatching async fetchers!", flush=True)
    with handle_sigint(AbortRequested):
        asyncio.run(amain(db_path, dur, opts.min_batch_size, opts.abort_low_rps))
    #
    end_x, end_y = Progress.next_coordinate
    if end_x == 0:
        end_x = Progress.DEFA_MAX_COORD[0]
        end_y -= 1
    end_coord = end_x, end_y

    print(
        f"{Progress.outstanding_count:_} outstanding jobs left. Last dispatched coordinate: {Progress.last_dispatch}"
    )
    print("Stats of this run:")
    pprint(ChangeStats)
    app_context.log(
        {
            "stats": ChangeStats,
            "range": f"{start_coord}~{end_coord}",
        }
    )


if __name__ == "__main__":
    options = get_options()
    lock_file = options.dbdir / Config.names.lock
    log_file = options.dbdir / Config.names.log
    with RetrieverApplication(lock_file=lock_file, log_file=lock_file) as app:
        main(app, options)