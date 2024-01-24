# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import pickle
import re
from asyncio import Task
from datetime import datetime
from pathlib import Path
from pprint import pprint
from typing import TYPE_CHECKING, Final, Optional, Protocol, TypedDict, Union, cast

import httpx

from retriever_v4 import RetrieverApplication, RetrieverProgress, dispatch_fetcher
from retriever_v4.names.xchg import export
from sl_maptools import CoordType, MapCoord, RegionsDBRecord3
from sl_maptools.fetchers.cap import BoundedNameFetcher
from sl_maptools.utils import ConfigReader, SLMapToolsConfig, handle_sigint, make_backup

if TYPE_CHECKING:
    from sl_maptools.fetchers import CookedResult


CONN_LIMIT: Final[int] = 80
# SEMA_SIZE: Final[int] = 180
HTTP2: Final[bool] = False
START_BATCH_SIZE: Final[int] = 600
BATCH_WAIT: Final[float] = 5.0
MAVG_SAMPLES: Final[int] = 5
ACCEPTABLE_STATUSCODES: Final[set[int]] = {0, 200, 403}

Config: SLMapToolsConfig = ConfigReader("config.toml")
DEFA_DB: Final[Path] = Path(Config.names.dir) / Config.names.db

Progress: RetrieverProgress

AbortRequested = asyncio.Event()

DataBase: dict[CoordType, RegionsDBRecord3] = {}


class ChangeStatsDict(TypedDict):
    """Define the fields of ChangeStats"""

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
    """Additional CLI options specified by this module"""

    dbpath: Path
    export: Union[Path, Ellipsis]
    auto_reset: bool


class OptionsProtocol(RetrieverNamesOptions, RetrieverApplication.Options, Protocol):
    """CLI Options to extract"""

    pass


def get_options() -> OptionsProtocol:
    """Extract options from CLI"""
    parser = argparse.ArgumentParser("retriever_v4.names")

    parser.add_argument("--dbpath", type=Path, default=DEFA_DB, help="Path to Regions Database file")
    parser.add_argument(
        "--export",
        metavar="YAML_file",
        type=Path,
        nargs="?",
        default=Ellipsis,  # This will be the value if --export is not specified at all
        # If --export is specified but no file name is given, the value will be None.
        # Hence is why Ellipsis is used, to differ between not specified, and specified but not given
        help="Export to YAML file on abort/completion. If not specified, then use default name.",
    )

    parser.add_argument(
        "--auto-reset",
        action="store_true",
        help=(
            f"If specified, retriever will wrap up back to maxrow "
            f"({RetrieverProgress.DEFA_MAX_COORD[1]}) upon finishing row 0"
        ),
    )

    RetrieverApplication.add_options(parser)

    _opts = parser.parse_args()

    return cast(OptionsProtocol, _opts)


def process(region: CookedResult) -> bool:
    """Process the unicode-decoded region data"""
    ts = datetime.now().astimezone()
    xy = region.coord.x, region.coord.y
    dbxy: RegionsDBRecord3 = DataBase.get(xy)

    def record_history() -> None:
        """Record the history of the region"""
        nonlocal dbxy
        seen_name = "" if region.result is None else region.result
        prev_name = dbxy["current_name"]
        dbxy["current_name"] = seen_name
        dbxy["last_check"] = ts
        if seen_name:
            dbxy["last_seen"] = ts
        history: dict[str, list[tuple[datetime, datetime]]] = dbxy["name_history3"]
        if seen_name not in history:
            ChangeStats["new"] += 1
            print("🉑", end="", flush=True)
            history[seen_name] = [(ts, ts)]
            return
        if seen_name != prev_name:
            if seen_name:
                if prev_name:
                    ChangeStats["changed"] += 1
                else:
                    ChangeStats["revived"] += 1
            else:
                ChangeStats["gone"] += 1
            print("🉑", end="", flush=True)
            history[seen_name].append((ts, ts))
        else:
            sts, _ = history[seen_name][-1]
            history[seen_name][-1] = (sts, ts)

    if region.result is None:
        if dbxy is None:
            return False
        assert isinstance(dbxy, dict)
        record_history()
    else:
        try:
            assert isinstance(region.result, str)
        except AssertionError:
            print(f"{region.result=} ({type(region.result)})")
            print(f"{region=}")
            raise
        if dbxy is None:
            dbxy: RegionsDBRecord3 = {
                "first_seen": ts,
                "last_seen": None,
                "last_check": None,
                "current_name": "",
                "name_history3": {},
                "sources": {"cap"},
            }
        assert isinstance(dbxy, dict)
        record_history()

    if xy in DataBase:
        DataBase[xy].update(cast(dict, dbxy))
    else:
        DataBase[xy] = dbxy
    return True


async def amain(db_path: Path, duration: int, min_batch_size: int, abort_low_rps: int) -> None:
    """Asynchronous main()"""
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(CONN_LIMIT * 3, client, cooked=True, cancel_flag=AbortRequested)
        shown = False

        def make_task(coord: CoordType) -> Task:
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        def pre_batch() -> None:
            nonlocal shown
            shown = False

        def process_result(fut_result: Optional[CookedResult]) -> bool:
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

        def post_batch() -> None:
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


def main(app_context: RetrieverApplication, opts: OptionsProtocol) -> None:  # noqa: D103
    global DataBase, Progress  # noqa: PLW0603

    dur = RetrieverApplication.calc_duration(opts)

    prog_file = opts.dbpath.parent / Config.names.progress
    Progress = RetrieverProgress(prog_file, auto_reset=opts.auto_reset)
    if Progress.outstanding_count:
        print(f"{Progress.outstanding_count} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")
        if Progress.next_y < 0:
            print("No rows left to process.")
            print(f"Delete the file {prog_file} to reset. (Or specify --auto-reset)")
            return
    print(f"Next coordinate: {Progress.next_coordinate}")

    if opts.dbpath.exists():
        print(f"Database {opts.dbpath} found, making backup ...", end="", flush=True)
        make_backup(opts.dbpath, 5)
        print(" done")
        with opts.dbpath.open("rb") as fin:
            DataBase = pickle.load(fin)  # noqa: S301
    print(f"DataBase already contains {len(DataBase)} regions.", flush=True)

    start_coord = Progress.next_coordinate
    #
    print("Dispatching async fetchers!", flush=True)
    with handle_sigint(AbortRequested):
        asyncio.run(amain(opts.dbpath, dur, opts.min_batch_size, opts.abort_low_rps))
    #
    end_x, end_y = Progress.next_coordinate
    if end_x == 0:
        end_x = Progress.DEFA_MAX_COORD[0]
        end_y -= 1
    end_coord = end_x, end_y

    print(f"{Progress.outstanding_count:_} outstanding jobs left. Last dispatched coordinate: {Progress.last_dispatch}")
    print("Stats of this run:")
    pprint(ChangeStats)
    app_context.log(
        {
            "stats": ChangeStats,
            "range": f"{start_coord}~{end_coord}",
        }
    )

    if opts.export is not Ellipsis:
        print("Exporting ... ", end="", flush=True)
        rslt = export(opts.dbpath, opts.export, quiet=True)
        print(f"=> {rslt}")


if __name__ == "__main__":
    options = get_options()
    lock_file = options.dbpath.parent / Config.names.lock
    log_file = options.dbpath.parent / Config.names.log
    with RetrieverApplication(lock_file=lock_file, log_file=lock_file, force=options.force) as app:
        main(app, options)
