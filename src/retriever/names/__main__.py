import argparse
import asyncio
import math
import pickle
import re
import statistics
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, TypedDict, cast, Protocol

import httpx

from retriever import RetrieverProgress, lock_file, handle_sigint
from sl_maptools import CoordType, MapCoord
from sl_maptools.fetchers import CookedResult
from sl_maptools.fetchers.cap import BoundedNameFetcher

CONN_LIMIT: Final[int] = 40
SEMA_SIZE: Final[int] = 120
HTTP2: Final[bool] = True
START_BATCH_SIZE: Final[int] = 600
BATCH_WAIT: Final[float] = 5.0
MAVG_SAMPLES: Final[int] = 5
ACCEPTABLE_STATUSCODES: Final[set[int]] = {0, 200, 403}

DEFA_DB_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\")
DB_NAME: Final[str] = "RegionsDB2.pkl"
PRGRS_NAME: Final[str] = "RegionsDB2Progress.yaml"
LOCK_NAME: Final[str] = "RegionsDB2.lock"

Progress: RetrieverProgress

AbortRequested = asyncio.Event()


class RegionsDBRecord(TypedDict):
    first_seen: str
    last_seen: str
    last_check: str
    current_name: str
    name_history: dict[str, list[str]]
    sources: set[str]


DataBase: dict[str, RegionsDBRecord] = {}


RE_HHMM = re.compile(r"^(\d{1,2}):(\d{1,2})$")


class OptionsProtocol(Protocol):
    dbdir: Path
    force: bool
    duration: int
    until: tuple[int, int]
    until_utc: tuple[int, int]


class HourMinute(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        m = RE_HHMM.match(values)
        if m is None:
            parser.error("Please enter time in 24h HH:MM format!")
        setattr(namespace, self.dest, (int(m.group(1)), int(m.group(2))))


def get_opts() -> OptionsProtocol:
    parser = argparse.ArgumentParser("retriever.names")

    parser.add_argument("--dbdir", type=Path, default=DEFA_DB_DIR)
    parser.add_argument("--force", action="store_true")

    parser.add_argument(
        "--auto-reset",
        action="store_true",
        help=f"If specified, retriever will wrap up back to maxrow ({RetrieverProgress.DEFA_MAX}) upon finishing row 0",
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


def process(tile: CookedResult):
    global DataBase

    ts = datetime.now().astimezone().isoformat(timespec="minutes")
    xy = f"{tile.coord.x},{tile.coord.y}"
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


async def amain(duration: int):
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(SEMA_SIZE, client, cooked=True, cancel_flag=AbortRequested)

        def make_task(coord: CoordType):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        start = time.monotonic()
        tasks: set[asyncio.Task] = {make_task(coord) async for coord in Progress.abatch(START_BATCH_SIZE)}
        if not tasks:
            print("No unseen jobs, exiting immediately!")
            return

        total = hasname_count = batch_size = 0
        done_last10: deque[int] = deque(maxlen=MAVG_SAMPLES)
        elapsed_last10: deque[float] = deque(maxlen=MAVG_SAMPLES)
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        while tasks:
            # Dispatch
            print(f"(+{batch_size}) {len(tasks)} async jobs =>", end=" ")
            start_batch = time.monotonic()
            done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
            elapsed_last10.append(time.monotonic() - start_batch)
            done_last10.append(len(done))
            total += len(done)
            batch_size = int(statistics.mean(done_last10)) * 3

            # Handle results
            c = e = 0
            shown = False
            for c, fut in enumerate(done, start=1):
                if exc := fut.exception():
                    e += 1
                    print(f"\n{fut.get_name()} raised Exception: <{type(exc)}> {exc}")
                    continue
                rslt: None | CookedResult = fut.result()
                if rslt is None or rslt.status_code not in ACCEPTABLE_STATUSCODES:
                    continue
                Progress.retire(rslt.coord)
                process(rslt)
                if rslt.result:
                    if not shown:
                        shown = True
                        print("🌐", end="")
                    hasname_count += 1
                    print(f"({rslt.coord.x},{rslt.coord.y}){rslt.result}", end=" ", flush=True)
            if c:
                Progress.save()
                if e == c:
                    print("\nLast batch all raised Exceptions!")
                    print("Cancelling the rest of the tasks...")
                    for t in pending_tasks:
                        t.cancel()
            if not shown:
                print("No names retrieved", end="")

            # Statistics
            elapsed = time.monotonic() - start
            avg_rate = sum(done_last10) / sum(elapsed_last10)
            print(
                f"\n  {elapsed:_.2f}s since start, {total:_} coords scanned "
                f"(mavg. {avg_rate:.2f} r/s), {hasname_count} regions retrieved"
            )

            # Next iteration
            tasks = pending_tasks
            if elapsed >= duration:
                AbortRequested.set()
            if not AbortRequested.is_set() and (2 * len(tasks)) < batch_size:
                async for coord in Progress.abatch(batch_size):
                    tasks.add(make_task(coord))


def main2(auto_reset: bool, db_dir: Path, duration: int, until: tuple[int, int], until_utc: tuple[int, int]):
    global DataBase, Progress

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

    Progress = RetrieverProgress((db_dir / PRGRS_NAME), auto_reset=auto_reset)
    if Progress.outstanding_count:
        print(f"{Progress.outstanding_count} jobs still outstanding from last session")
    else:
        print("No outstanding jobs from last session.")
        if Progress.next_y < 0:
            print("No rows left to process.")
            print(f"Delete the file {db_dir / PRGRS_NAME} to reset. (Or specify --auto-reset)")
            return
    print(f"Next coordinate: {Progress.next_coordinate}")

    db_path = db_dir / DB_NAME
    if db_path.exists():
        with db_path.open("rb") as fin:
            DataBase = pickle.load(fin)
    print(f"DataBase already contains {len(DataBase)} regions.")

    with handle_sigint(AbortRequested):
        asyncio.run(amain(dur))

    print(f"{Progress.outstanding_count:_} outstanding jobs left. Last dispatched coordinate: {Progress.last_dispatch}")


def main(auto_reset: bool, force: bool, dbdir: Path, duration: int, until: tuple[int, int], until_utc: tuple[int, int]):
    dbdir.mkdir(parents=True, exist_ok=True)
    with lock_file(dbdir / LOCK_NAME, force):
        main2(auto_reset, dbdir, duration, until, until_utc)


if __name__ == '__main__':
    opts = get_opts()
    main(**vars(opts))
