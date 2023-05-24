# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import asyncio
import multiprocessing as MP
import multiprocessing.managers as MPMgrs
import multiprocessing.pool as MPPool
import pickle
import queue
import signal
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from pprint import pprint
from typing import Final, Optional, Protocol, TypedDict, Union, cast

import httpx

from retriever_v4 import RetrieverApplication, RetrieverProgress
from retriever_v4.names.xchg import export
from sl_maptools import CoordType, MapCoord, RegionsDBRecord3
from sl_maptools.fetchers import CookedResult
from sl_maptools.fetchers.cap import BoundedNameFetcher
from sl_maptools.utils import ConfigReader, Settable, SLMapToolsConfig, handle_sigint

WORKERS: Final[int] = 2
CONN_LIMIT: Final[int] = 80
HTTP2: Final[bool] = False
START_BATCH_SIZE: Final[int] = 600
BATCH_WAIT: Final[float] = 5.0
WMA_SAMPLES: Final[int] = 5
ACCEPTABLE_STATUSCODES: Final[set[int]] = {0, 200, 403}

Config: SLMapToolsConfig = ConfigReader("config.toml")
DEFA_DB: Final[Path] = Path(Config.names.dir) / Config.names.db


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


class RetrieverNamesOptions(Protocol):
    dbpath: Path
    export: Union[Path, Ellipsis]
    auto_reset: bool


class OptionsProtocol(RetrieverNamesOptions, RetrieverApplication.Options, Protocol):
    pass


def get_options() -> OptionsProtocol:
    parser = argparse.ArgumentParser("retriever_v4.names")

    parser.add_argument(
        "--dbpath", type=Path, default=DEFA_DB, help="Path to Regions Database file"
    )
    parser.add_argument(
        "--export",
        metavar="YAML_file",
        type=Path,
        nargs="?",
        default=Ellipsis,  # This will be the value if --export is not specified at all
        # If --export is specified but no file name is given, the value will be None.
        # Hence, is why Ellipsis is used, to differ between not specified, and specified but not given
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


def integrator(in_queue: MP.Queue, dbpath: Path, change_stats: ChangeStatsDict):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    MP.current_process().name = "Integrator"
    if dbpath.exists():
        with dbpath.open("rb") as fin:
            database: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)
    else:
        dbpath.parent.mkdir(parents=True, exist_ok=True)
        database = {}
    dbxy: RegionsDBRecord3

    def record_history():
        nonlocal dbxy
        seen_name = "" if result is None else result
        prev_name = dbxy["current_name"]
        dbxy["current_name"] = seen_name
        dbxy["last_check"] = ts
        if seen_name:
            dbxy["last_seen"] = ts
        history: dict[str, list[tuple[datetime, datetime]]] = dbxy["name_history3"]
        if seen_name not in history:
            change_stats["new"] += 1
            print("🉑", end="", flush=True)
            history[seen_name] = [(ts, ts)]
            return
        if seen_name != prev_name:
            if seen_name:
                if prev_name:
                    change_stats["changed"] += 1
                else:
                    change_stats["revived"] += 1
            else:
                change_stats["gone"] += 1
            print("🉑", end="", flush=True)
            history[seen_name].append((ts, ts))
        else:
            sts, _ = history[seen_name][-1]
            history[seen_name][-1] = (sts, ts)

    total = 0
    count = 0
    st = time.monotonic()
    dones: deque[float] = deque(maxlen=WMA_SAMPLES)
    elapses: deque[float] = deque(maxlen=WMA_SAMPLES)
    while True:
        job: Union[None, Ellipsis, CookedResult] = in_queue.get()
        if job is None:
            break
        if job is Ellipsis:
            continue

        total += 1
        count += 1
        xy = job.coord
        result = job.result
        ts = datetime.now().astimezone()
        dbxy: RegionsDBRecord3 = database.get(xy)

        skip_db_upd = False
        if result is None:
            if dbxy is not None:
                assert isinstance(dbxy, dict)
                record_history()
            else:
                skip_db_upd = True
        else:
            try:
                assert isinstance(result, str)
            except AssertionError:
                print("saver ERROR:")
                print(f"{result=} ({type(result)})")
                print(f"{job=}")
                skip_db_upd = True
            else:
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

        if not skip_db_upd:
            if xy in database:
                database[xy].update(cast(dict, dbxy))
            else:
                database[xy] = dbxy

        elapsed = time.monotonic() - st
        if elapsed > BATCH_WAIT:
            dones.append(count)
            elapses.append(elapsed)
            rate = sum(dones) / sum(elapses)
            print(f"{total} names retrieved @ mavg. {rate:_.2f} rps")
            with dbpath.open("wb") as fout:
                pickle.dump(database, fout)
            st = time.monotonic()
            count = 0


async def aretriever(in_queue: MP.Queue, out_queue: MP.Queue, abort_flag: Settable):
    limits = httpx.Limits(
        max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT
    )
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedNameFetcher(
            CONN_LIMIT * 3, client, cooked=True, cancel_flag=abort_flag
        )

        def make_task(coord: CoordType):
            return asyncio.create_task(
                fetcher.async_fetch(MapCoord(*coord)), name=str(coord)
            )

        tasks: set[asyncio.Task] = set()
        job = in_queue.get()
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        while True:
            if job is None:
                break
            if job is not Ellipsis:
                cmd, det = job
                if cmd == "row":
                    for x in range(0, 2101):
                        co = x, det
                        tasks.add(make_task(co))
                elif cmd == "set":
                    tasks.update(make_task(co) for co in det)
                elif cmd == "single":
                    tasks.add(make_task(det))

            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=BATCH_WAIT)
                for fut in done:
                    if exc := fut.exception():
                        print(f"\n{fut.get_name()} Exception: <{type(exc)}>{exc}")
                        continue
                    fut_result: Optional[CookedResult] = fut.result()
                    if fut_result is None:
                        continue
                    if fut_result.status_code not in ACCEPTABLE_STATUSCODES:
                        ChangeStats["failure"] += 1
                        continue
                    out_queue.put(fut_result)
                tasks = pending

            job = Ellipsis
            if not abort_flag.is_set():
                if len(tasks) < 1050:
                    try:
                        job = in_queue.get_nowait()
                    except queue.Empty:
                        pass


def retriever(in_queue: MP.Queue, out_queue: MP.Queue, abort_flag: Settable):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    asyncio.run(aretriever(in_queue, out_queue, abort_flag))


def main(opts: OptionsProtocol):
    dbpath = Path(opts.dbpath)
    mgr: MPMgrs.SyncManager
    with MP.Manager() as mgr:
        fetch_queue: MP.Queue = mgr.Queue()
        result_queue: MP.Queue = mgr.Queue()
        stats = cast(ChangeStatsDict, mgr.dict())
        abort_flag = MP.Event()
        args_r = fetch_queue, result_queue, abort_flag
        args_i = result_queue, dbpath, stats
        pool_r: MPPool.Pool
        pool_i: MPPool.Pool
        with MP.Pool(
            WORKERS, initializer=retriever, initargs=args_r
        ) as pool_r, MP.Pool(1, initializer=integrator, initargs=args_i) as pool_i:
            with handle_sigint(abort_flag):
                for row in range(2100, -1, -1):
                    fetch_queue.put(("row", row))
                print(
                    "### All jobs queued to Retriever Workers, waiting until all jobs consumed ###",
                    flush=True,
                )
                while not fetch_queue.empty():
                    time.sleep(5)
                print(
                    "### All jobs consumed, pausing to allow workers to finish ###",
                    flush=True,
                )
                time.sleep(10)

            print("Teling Retriever Workers to end")
            pool_r.close()
            for _ in range(0, WORKERS):
                fetch_queue.put(None)
            print("Waiting Retriever Workers to join ... ", end="", flush=True)
            pool_r.join()
            print("joined")

            print("Waiting until integration finishes", flush=True)
            while not result_queue.empty():
                time.sleep(1)

            print("Teling Integration Worker to end")
            pool_i.close()
            result_queue.put(None)
            print("Waiting Integration Worker to join ... ", end="", flush=True)
            pool_i.join()
            print("joined.")

        final_stats = dict(stats)

    pprint(final_stats)

    if opts.export is not Ellipsis:
        print("Exporting ... ", end="", flush=True)
        rslt = export(opts.dbpath, opts.export, quiet=True)
        print(f"=> {rslt}")


if __name__ == "__main__":
    options = get_options()
    lock_file = options.dbpath.parent / Config.names.lock
    log_file = options.dbpath.parent / Config.names.log
    with RetrieverApplication(
        lock_file=lock_file, log_file=lock_file, force=options.force
    ) as app:
        main(options)
