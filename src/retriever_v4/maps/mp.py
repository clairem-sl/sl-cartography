# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import asyncio
import multiprocessing as MP
import multiprocessing.managers as MPMgr
import multiprocessing.pool as mp_pool
import multiprocessing.shared_memory as MPSharedMem
import pickle
import queue
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Final, Iterable, NamedTuple, Optional, Protocol, TypedDict, Union, cast

import httpx
from ruamel.yaml import YAML, RoundTripRepresenter

from sl_maptools import CoordType, MapCoord, Settable
from sl_maptools.fetchers.map import BoundedMapFetcher
from sl_maptools.utils import ConfigReader, handle_sigint, make_backup

UNKNOWN_COORD: Final[MapCoord] = MapCoord(-1, -1)

BATCH_WAIT: Final[int] = 1
CONN_LIMIT: Final[int] = 80
HTTP2: Final[bool] = True

INFO_EVERY: Final[float] = 5.0

RETR_WORKERS: Final[int] = max((MP.cpu_count() - 2) * 2, 2)
SAVE_WORKERS: Final[int] = min((RETR_WORKERS // 2), 4)

START_ROW: Final[int] = 2100
COLS_PER_ROW: Final[int] = 2100

Config = ConfigReader("config.toml")
AbortRequested: Settable = MP.Event()


class MPMapOptions(Protocol):
    mapdir: Path
    workers: int
    savers: int


def get_options() -> MPMapOptions:
    parser = argparse.ArgumentParser("retriever.maps.mp")

    parser.add_argument("--mapdir", type=Path, default=Path(Config.maps.mp_dir))
    parser.add_argument("--workers", type=int, default=RETR_WORKERS)
    parser.add_argument("--savers", type=int, default=SAVE_WORKERS)

    _opts = parser.parse_args()
    return cast(MPMapOptions, _opts)


class QSaveJob(TypedDict):
    coord: MapCoord
    tsf: str
    shm: MPSharedMem.SharedMemory


class QResult(NamedTuple):
    entity: str
    coord: MapCoord
    exc: Optional[Exception]


def saver(
    mapdir: Path,
    incoming_queue: MP.Queue,
    result_queue: MP.Queue,
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    mapdir.mkdir(parents=True, exist_ok=True)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"Saver-{num}"
    MP.current_process().name = myname

    result: QResult
    while True:
        if incoming_queue.empty():
            time.sleep(1)
            continue
        item = incoming_queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        regmap: QSaveJob = cast(QSaveJob, item)
        coord: MapCoord = regmap["coord"]
        # shm = MPSharedMem.SharedMemory(regmap["shm_name"])
        shm = regmap["shm"]
        tsf = regmap["tsf"]
        targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
        try:
            with targf.open("wb") as fout:
                # noinspection PyTypeChecker
                fout.write(shm.buf)
            shm.close()
            shm.unlink()
            result = QResult(myname, coord, None)
        except Exception as e:
            print(f"\nERR: {myname}:{type(e)}:{e}", file=sys.stderr, flush=True)
            result = QResult(myname, coord, e)
        result_queue.put(result)


async def aretrieve(
    in_queue: MP.Queue,
    out_queue: MP.Queue,
    disp_queue: MP.Queue,
    result_queue: MP.Queue,
    abort_flag: Settable,
):
    _half_cols = COLS_PER_ROW // 2
    _myname = MP.current_process().name
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(CONN_LIMIT * 3, client, cooked=False, cancel_flag=abort_flag)

        def make_task(coord: CoordType):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        tasks: set[asyncio.Task] = set()
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        job: Union[Ellipsis, tuple[str, Union[CoordType, Iterable[CoordType], int]]] = in_queue.get()
        co: CoordType
        while True:
            if job is not None and job is not Ellipsis:
                cmd, det = job
                if cmd == "single":
                    disp_queue.put([det])
                    tasks.add(make_task(det))
                    msg = f"single({det})"
                elif cmd == "set":
                    tasks.update(make_task(co) for co in det)
                    disp_queue.put(det)
                    msg = f"set(...{len(det)}...)"
                elif cmd == "row":
                    d = []
                    for x in range(0, COLS_PER_ROW + 1):
                        co = x, det
                        d.append(co)
                        tasks.add(make_task(co))
                    disp_queue.put(d)
                    msg = f"row({det})"
                print(MP.current_process().name, msg)

            if tasks:
                done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
                disp_queue.put(len(done))

                for fut in done:
                    if (exc := fut.exception()) is not None:
                        print(f"{_myname}:{fut.get_name()} ERR <{type(exc)}>{exc}", file=sys.stderr, flush=True)
                        _err = QResult(f"{_myname}:{fut.get_name()}", UNKNOWN_COORD, cast(Exception, exc))
                        result_queue.put(_err)
                        continue
                    fut_result = fut.result()
                    if fut_result is None:
                        continue
                    if not fut_result.result:
                        _retire: QResult = QResult(_myname, fut_result.coord, None)
                        result_queue.put(_retire)
                        continue
                    assert isinstance(fut_result.result, bytes)
                    shm = MPSharedMem.SharedMemory(create=True, size=len(fut_result.result))
                    shm.buf[:] = fut_result.result
                    save: QSaveJob = {
                        "coord": fut_result.coord,
                        "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                        "shm": shm,
                    }
                    out_queue.put(save)
                    shm.close()

                tasks = pending_tasks

            if abort_flag.is_set():
                job = None
            if job is None:
                if not tasks:
                    break
                continue

            job = Ellipsis
            if len(tasks) > _half_cols:
                continue
            try:
                job = in_queue.get_nowait()
            except queue.Empty:
                time.sleep(1)

    print(f"{MP.current_process().name} done")


def retrieve(
    in_queue: MP.Queue,
    out_queue: MP.Queue,
    disp_queue: MP.Queue,
    retire_queue: MP.Queue,
    abort_flag: Settable,
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"Retriever-{num}"
    MP.current_process().name = myname
    asyncio.run(aretrieve(in_queue, out_queue, disp_queue, retire_queue, abort_flag))


class ProgressDict(TypedDict):
    next_row: Optional[int]
    backlog: set[CoordType]


class ProgressionDict(TypedDict):
    start: Optional[datetime]
    done: int
    last: Optional[datetime]


def main(opts: MPMapOptions):
    start = time.monotonic()

    pool_r: mp_pool.Pool
    pool_s: mp_pool.Pool

    progress_file = opts.mapdir / Config.maps.mp_progress
    if progress_file.exists():
        with progress_file.open("rb") as fin:
            progress: ProgressDict = pickle.load(fin)
        if progress["next_row"] is None:
            progress["next_row"] = -1
    else:
        progress = {
            "next_row": START_ROW,
            "backlog": set(),
        }
    print(f"Backlog from previous run: {len(progress['backlog']):_}\nNext row after backlog: {progress['next_row']}")

    errs: list[QResult] = []
    mgr: MPMgr.SyncManager
    with MP.Manager() as mgr:
        coord_queue: MP.Queue = mgr.Queue()
        save_queue: MP.Queue = mgr.Queue(maxsize=4000)
        dispatched_queue: MP.Queue = mgr.Queue()
        result_queue: MP.Queue = mgr.Queue()

        r_args = (
            coord_queue,
            save_queue,
            dispatched_queue,
            result_queue,
            AbortRequested,
        )
        s_args = (Path(Config.maps.mp_dir), save_queue, result_queue)

        progression: dict[int, ProgressionDict] = {
            y: {
                "start": None,
                "done": 0,
                "last": None
            }
            for y in range(0, 2101)
        }
        outstanding: set[CoordType] = set()
        total: int = 0
        count: int = 0

        def flush_dispatched_queue():
            nonlocal count
            try:
                while True:
                    di = dispatched_queue.get_nowait()
                    if isinstance(di, list):
                        outstanding.update(cast(list[CoordType], di))
                    elif isinstance(di, int):
                        count += di
            except queue.Empty:
                pass

        def flush_result_queue():
            nonlocal total
            try:
                while True:
                    rslt: QResult = result_queue.get_nowait()
                    if rslt.exc is None:
                        outstanding.discard(rslt.coord)
                        if rslt.entity.startswith("Saver"):
                            total += 1
                        else:
                            _, y = rslt.coord
                            _prog = progression[y]
                            if _prog["start"] is None:
                                _prog["start"] = datetime.now()
                            _prog["done"] += 1
                            _prog["last"] = datetime.now()
                    else:
                        errs.append(rslt)
            except queue.Empty:
                pass

        with MP.Pool(opts.workers, initializer=retrieve, initargs=r_args) as pool_r, MP.Pool(
            opts.savers, initializer=saver, initargs=s_args
        ) as pool_s:
            with handle_sigint(AbortRequested):
                backlog = sorted(progress["backlog"], key=lambda i: (i[1], i[0]))
                if backlog:
                    _chunksize = (len(backlog) // opts.workers) + 1
                    _chunksize = min(2000, _chunksize)
                    _i = 0
                    while _i < len(backlog):
                        coord_queue.put(("set", backlog[_i : (_i + _chunksize)]))
                        _i += _chunksize
                for row in range(progress["next_row"], -1, -1):
                    coord_queue.put(("row", row))
                tm: float = time.monotonic()
                while not coord_queue.empty() and not AbortRequested.is_set():
                    flush_dispatched_queue()
                    flush_result_queue()
                    elapsed = time.monotonic() - tm
                    if elapsed >= INFO_EVERY:
                        rate = count / elapsed
                        print(f"{count:_} coords checked, at {rate:_.2f}rps, {total:_} retrieved", flush=True)
                        count = 0
                        tm = time.monotonic()

                print("Telling retriever workers to end")
                pool_r.close()
                for _ in range(opts.workers):
                    coord_queue.put(None)
                print("Joining retriever workers")
                pool_r.join()

                print("Flushing coord_queue")
                next_row = None
                try:
                    cmd, det = coord_queue.get_nowait()
                    if cmd == "row":
                        if next_row is None:
                            next_row = det
                    elif cmd == "single":
                        outstanding.add(det)
                    elif cmd == "set":
                        outstanding.update(det)
                except queue.Empty:
                    pass

                print("Telling saver workers to end")
                pool_s.close()
                for _ in range(opts.savers):
                    save_queue.put(None)
                print("Joining saver workers")
                pool_s.join()

                print("Flushing dispatched_queue")
                flush_dispatched_queue()

                print("Flushing result_queue")
                flush_result_queue()

    if errs:
        print("During retrieval, the following errors are seen:", flush=True)
        time.sleep(1)
        for entity, coord, exc in errs:
            print(f"    {entity} <{type(exc)}>{exc}", file=sys.stderr)
        time.sleep(1)
        print(f"  A total of {len(errs)} errors")

    progress = {
        "next_row": next_row,
        "backlog": outstanding,
    }
    with progress_file.open("wb") as fout:
        pickle.dump(progress, fout)

    normalized_time_per_row: dict[int, float] = {}
    for y, prog in progression.items():
        n = prog["done"]
        if n == 0:
            continue
        if prog["start"] is None or prog["last"] is None:
            continue
        delta = prog["last"] - prog["start"]
        if delta.seconds < 0.1:
            continue
        normalized_time_per_row[y] = 2100 * delta.seconds / n
    yaml = YAML(typ="safe")
    yaml.Representer = RoundTripRepresenter
    perfdata: dict[datetime, dict[int, float]] = {}
    performance_file = opts.mapdir / "performance.yaml"
    if performance_file.exists():
        make_backup(performance_file)
        with performance_file.open("rt") as fin:
            perfdata = yaml.load(fin)
    perfdata[datetime.now().astimezone()] = normalized_time_per_row
    with performance_file.open("wt") as fout:
        yaml.dump(perfdata, fout)

    print(f"{len(outstanding):_} coordinates in backlog, next row will be {next_row}")

    finish = time.monotonic()
    print(f"Finished in {finish - start:_.2f}s on {datetime.now().isoformat(timespec='minutes')}")


if __name__ == "__main__":
    options = get_options()
    main(options)
