# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import asyncio
import multiprocessing as MP
import multiprocessing.managers as MPMgr
import multiprocessing.pool as mp_pool
import multiprocessing.shared_memory as MPSharedMem
import queue
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Final, NamedTuple, Optional, TypedDict, Union, cast

import httpx

from retriever_v4 import handle_sigint
from sl_maptools import CoordType, MapCoord, Settable
from sl_maptools.fetchers.map import BoundedMapFetcher
from sl_maptools.utils import ConfigReader

BATCH_WAIT: Final[int] = 5
CONN_LIMIT: Final[int] = 80
HTTP2: Final[bool] = True

RETR_WORKERS: Final[int] = 12
SAVE_WORKERS: Final[int] = 4

Config = ConfigReader("config.toml")
AbortRequested: Settable = MP.Event()


class QSaveJob(TypedDict):
    coord: MapCoord
    tsf: str
    shm_name: str


class QSaveResult(NamedTuple):
    coord: MapCoord
    exc: Optional[Exception]


class SharedMemoryAllocator:
    def __init__(self, manager: MPMgr.SharedMemoryManager):
        self.mgr = manager
        self.allocations: dict[CoordType, MPSharedMem.SharedMemory] = {}

    def new(self, coord: CoordType, data: bytes) -> MPSharedMem.SharedMemory:
        shm = self.mgr.SharedMemory(len(data))
        shm.buf[:] = data
        self.allocations[coord] = shm
        return shm

    def retire(self, coord: CoordType) -> None:
        shm = self.allocations[coord]
        shm.close()
        shm.unlink()
        del self.allocations[coord]


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

    result: QSaveResult
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
        shm = MPSharedMem.SharedMemory(regmap["shm_name"])
        tsf = regmap["tsf"]
        targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
        try:
            with targf.open("wb") as fout:
                # noinspection PyTypeChecker
                fout.write(shm.buf)
            shm.close()
            shm.unlink()
            result = QSaveResult(coord, None)
        except Exception as e:
            print(f"\nERR: {myname}:{type(e)}:{e}")
            result = QSaveResult(coord, e)
        result_queue.put(result)


async def aretrieve(in_queue: MP.Queue, out_queue: MP.Queue, disp_queue: MP.Queue, abort_flag: Settable):
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(CONN_LIMIT * 3, client, cooked=False, cancel_flag=abort_flag)

        def make_task(coord: CoordType):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        tasks: set[asyncio.Task] = set()
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        job: Union[Ellipsis, tuple[str, int, int]] = in_queue.get()
        while True:
            if job is None:
                break
            if job is not Ellipsis:
                print(MP.current_process().name, job)
                cmd, x, y = cast(tuple[str, int, int], job)
                if cmd == "single":
                    disp_queue.put([(x, y)])
                    tasks.add(make_task((x, y)))
                elif cmd == "row":
                    d = []
                    for x in range(0, 2101):
                        co = x, y
                        d.append(co)
                        tasks.add(make_task(co))
                    disp_queue.put(d)

            if tasks:
                done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
                disp_queue.put(len(done))

                for fut in done:
                    fut_result = fut.result()
                    if fut_result is None:
                        continue
                    if not fut_result.result:
                        continue
                    assert isinstance(fut_result.result, bytes)
                    shm = MPSharedMem.SharedMemory(create=True, size=len(fut_result.result))
                    shm.buf[:] = fut_result.result
                    save: QSaveJob = {
                        "coord": fut_result.coord,
                        "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                        "shm_name": shm.name,
                    }
                    out_queue.put(save)
                    shm.close()

                tasks = pending_tasks

            job = Ellipsis
            if not abort_flag.is_set():
                if len(tasks) < 1050:
                    try:
                        job = in_queue.get_nowait()
                    except queue.Empty:
                        pass
            else:
                if not tasks:
                    break
    print(f"{MP.current_process().name} done")


def retrieve(in_queue: MP.Queue, out_queue: MP.Queue, disp_queue: MP.Queue, abort_flag: Settable):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"Retriever-{num}"
    MP.current_process().name = myname
    asyncio.run(aretrieve(in_queue, out_queue, disp_queue, abort_flag))


def main():
    pool_r: mp_pool.Pool
    pool_s: mp_pool.Pool

    mgr: MPMgr.SyncManager
    with MP.Manager() as mgr:
        coord_queue: MP.Queue = mgr.Queue()
        save_queue: MP.Queue = mgr.Queue()
        dispatched_queue: MP.Queue = mgr.Queue()
        result_queue: MP.Queue = mgr.Queue()

        r_args = (
            coord_queue,
            save_queue,
            dispatched_queue,
            AbortRequested,
        )
        s_args = (Path(Config.maps.dir), save_queue, result_queue)

        outstanding: set[CoordType] = set()
        count: int = 0
        total: int = 0

        def flush_dispatched_queue():
            nonlocal total
            try:
                while True:
                    di = dispatched_queue.get_nowait()
                    if isinstance(di, list):
                        outstanding.update(cast(list[CoordType], di))
                    elif isinstance(di, int):
                        total += di
            except queue.Empty:
                pass

        def flush_result_queue():
            nonlocal count
            try:
                while True:
                    rslt: QSaveResult = result_queue.get_nowait()
                    if rslt.exc is None:
                        outstanding.discard(rslt.coord)
                        count += 1
            except queue.Empty:
                pass

        with MP.Pool(RETR_WORKERS, initializer=retrieve, initargs=r_args) as pool_r, MP.Pool(
            SAVE_WORKERS, initializer=saver, initargs=s_args
        ) as pool_s:
            with handle_sigint(AbortRequested):
                for row in range(2100, -1, -1):
                    coord_queue.put(("row", -1, row))
                tm: float = time.monotonic()
                while not coord_queue.empty() and not AbortRequested.is_set():
                    flush_dispatched_queue()
                    flush_result_queue()
                    elapsed = time.monotonic() - tm
                    if elapsed >= 5.0:
                        rate = total / elapsed
                        print(f"{total:_} coords checked, at {rate:_.2f}rps, {count:_} retrieved", flush=True)
                        total = 0
                        tm = time.monotonic()

                print("Telling retriever workers to end")
                pool_r.close()
                for _ in range(RETR_WORKERS):
                    coord_queue.put(None)
                print("Joining retriever workers")
                pool_r.join()

                print("Flushing coord_queue")
                while not coord_queue.empty():
                    coord_queue.get()

                print("Telling saver workers to end")
                pool_s.close()
                for _ in range(SAVE_WORKERS):
                    save_queue.put(None)
                print("Joining saver workers")
                pool_s.join()

                print("Flushing dispatched_queue")
                flush_dispatched_queue()

                print("Flushing result_queue")
                flush_result_queue()

    print(outstanding)


if __name__ == "__main__":
    main()