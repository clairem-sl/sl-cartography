import argparse
import asyncio
import pickle
import re
from datetime import datetime
from pathlib import Path
from pprint import pprint
from typing import Final, Protocol, TypedDict, cast

import httpx

from retriever import (
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

CONN_LIMIT: Final[int] = 80
# SEMA_SIZE: Final[int] = 180
HTTP2: Final[bool] = False
START_BATCH_SIZE: Final[int] = 600
BATCH_WAIT: Final[float] = 5.0
MAVG_SAMPLES: Final[int] = 5
ACCEPTABLE_STATUSCODES: Final[set[int]] = {0, 200, 403}

DEFA_DB_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\")
DB_NAME: Final[str] = "RegionsDB2.pkl"
PRGRS_NAME: Final[str] = "RegionsDB2Progress.yaml"
LOCK_NAME: Final[str] = "RegionsDB2.lock"
LOGFILE_NAME: Final[str] = "RegionsDB2.log.yaml"

Progress: RetrieverProgress

AbortRequested = asyncio.Event()

DataBase: dict[CoordType, RegionsDBRecord] = {}


class ChangeStatsDict(TypedDict):
    new: int
    changed: int
    gone: int
    revived: int


ChangeStats: ChangeStatsDict = {
    "new": 0,
    "changed": 0,
    "gone": 0,
    "revived": 0,
}


RE_HHMM = re.compile(r"^(\d{1,2}):(\d{1,2})$")


class RetrieverNamesOptions(Protocol):
    dbdir: Path
    force: bool
    auto_reset: bool


class OptionsProtocol(RetrieverNamesOptions, TimeOptions, Protocol):
    pass


def get_options() -> OptionsProtocol:
    parser = argparse.ArgumentParser("retriever.names")

    parser.add_argument("--dbdir", type=Path, default=DEFA_DB_DIR)
    parser.add_argument("--force", action="store_true")

    parser.add_argument(
        "--auto-reset",
        action="store_true",
        help=(
            f"If specified, retriever will wrap up back to maxrow "
            f"({RetrieverProgress.DEFA_MAX_COORD[1]}) upon finishing row 0"
        ),
    )

    add_timeoptions(parser)

    _opts = parser.parse_args()

    return cast(OptionsProtocol, _opts)


def process(tile: CookedResult):
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
            return
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


async def amain(db_path: Path, duration: int):
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
            if fut_result.status_code not in ACCEPTABLE_STATUSCODES:
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
            process(fut_result)
            Progress.retire(fut_result.coord)
            return True

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
        )


def main(app_context: RetrieverApplication, opts: OptionsProtocol):
    global DataBase, Progress

    dur = calc_duration(opts)

    Progress = RetrieverProgress((opts.dbdir / PRGRS_NAME), auto_reset=opts.auto_reset)
    if Progress.outstanding_count:
        print(f"{Progress.outstanding_count} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")
        if Progress.next_y < 0:
            print("No rows left to process.")
            print(
                f"Delete the file {opts.dbdir / PRGRS_NAME} to reset. (Or specify --auto-reset)"
            )
            return
    print(f"Next coordinate: {Progress.next_coordinate}")

    db_path = opts.dbdir / DB_NAME
    if db_path.exists():
        with db_path.open("rb") as fin:
            DataBase = pickle.load(fin)
    print(f"DataBase already contains {len(DataBase)} regions.")

    start_coord = Progress.next_coordinate
    with handle_sigint(AbortRequested):
        asyncio.run(amain(db_path, dur))
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
    lock_file = options.dbdir / LOCK_NAME
    log_file = options.dbdir / LOGFILE_NAME
    with RetrieverApplication(lock_file=lock_file, log_file=lock_file) as app:
        main(app, options)
