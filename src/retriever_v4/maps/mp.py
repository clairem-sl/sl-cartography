# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import asyncio
import multiprocessing as MP
import multiprocessing.pool as mp_pool
import multiprocessing.managers as MPMgr
import multiprocessing.shared_memory as MPSharedMem
import queue
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import cast, Final, TypedDict, NamedTuple, Optional, Union

import httpx

from sl_maptools import CoordType, MapCoord
from sl_maptools.fetchers.map import BoundedMapFetcher
from sl_maptools.utils import ConfigReader

BATCH_WAIT: Final[int] = 5
CONN_LIMIT: Final[int] = 20
HTTP2: Final[bool] = True

Config = ConfigReader("config.toml")
AbortRequested = MP.Event()


class QJob(TypedDict):
    coord: MapCoord
    tsf: str
    buf: bytes


class QResult(NamedTuple):
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
    myname = f"SaverWorker-{num}"
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

        regmap: QJob = cast(QJob, item)
        coord: MapCoord = regmap["coord"]
        blob: bytes = regmap["buf"]
        tsf = regmap["tsf"]
        targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
        try:
            with targf.open("wb") as fout:
                fout.write(blob)
            result = QResult(coord, None)
        except Exception as e:
            print(f"\nERR: {myname}:{type(e)}:{e}")
            result = QResult(coord, e)
        result_queue.put(result)


async def aretrieve(in_queue: MP.Queue, out_queue: MP.Queue, disp_queue: MP.Queue):
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(CONN_LIMIT * 3, client, cooked=False, cancel_flag=AbortRequested)

        def make_task(coord: CoordType):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        tasks: set[asyncio.Task] = set()
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        job: Union[Ellipsis, QJob] = in_queue.get()
        while True:
            if job is None:
                break
            if job is not Ellipsis:
                print(job)
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
                    job: QJob = {
                        "coord": fut_result.coord,
                        "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                        "buf": fut_result.result,
                    }
                    out_queue.put(job)

                tasks = pending_tasks

            if len(tasks) < 1050:
                try:
                    job = in_queue.get_nowait()
                except queue.Empty:
                    job = Ellipsis
            else:
                job = Ellipsis


def retrieve(in_queue: MP.Queue, out_queue: MP.Queue, disp_queue: MP.Queue):
    asyncio.run(aretrieve(in_queue, out_queue, disp_queue))


def main():
    pool_r: mp_pool.Pool
    pool_s: mp_pool.Pool

    mgr: MPMgr.SyncManager
    with MP.Manager() as mgr:
        coord_queue = mgr.Queue()
        save_queue = mgr.Queue()
        dispatched_queue = mgr.Queue()
        result_queue = mgr.Queue()

        r_args = (
            coord_queue,
            save_queue,
            dispatched_queue,
        )
        s_args = (Path(Config.maps.dir), save_queue, result_queue)

        outstanding: set[CoordType] = set()
        with MP.Pool(12, initializer=retrieve, initargs=r_args) as pool_r, MP.Pool(
            4, initializer=saver, initargs=s_args
        ) as pool_s:
            for row in range(1000, -1, -1):
                coord_queue.put(("row", -1, row))
            tm: Optional[float] = None
            count: int = 0
            total: int = 0
            while not coord_queue.empty():
                if tm is None:
                    tm = time.monotonic()
                try:
                    while True:
                        di = dispatched_queue.get_nowait()
                        if isinstance(di, list):
                            outstanding.update(di)
                        elif isinstance(di, int):
                            total += di
                except queue.Empty:
                    pass
                try:
                    while True:
                        rslt: QResult = result_queue.get_nowait()
                        if rslt.exc is None:
                            outstanding.discard(rslt.coord)
                            count += 1
                except queue.Empty:
                    pass
                elapsed = time.monotonic() - tm
                if elapsed >= 5.0:
                    rate = total / elapsed
                    print(f"{total:_} coords checked, at {rate:_.2f}rps, {count:_} retrieved", flush=True)
                    total = 0
                    tm = time.monotonic()


if __name__ == "__main__":
    main()
