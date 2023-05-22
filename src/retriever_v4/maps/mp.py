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
from typing import cast, Final, TypedDict, NamedTuple, Optional

import httpx

from sl_maptools import CoordType, MapCoord
from sl_maptools.fetchers.map import BoundedMapFetcher
from sl_maptools.utils import ConfigReader

BATCH_WAIT: Final[int] = 5
CONN_LIMIT: Final[int] = 20
HTTP2: Final[bool] = True

Config = ConfigReader("config.toml")
AbortRequest = MP.Event()


class QJob(TypedDict):
    coord: MapCoord
    tsf: str
    shm: MPSharedMem.SharedMemory


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

    result: Optional[QResult] = None
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
        shm: MPSharedMem.SharedMemory = regmap["shm"]
        blob = cast(bytes, shm.buf)
        tsf = regmap["tsf"]
        targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
        try:
            with targf.open("wb") as fout:
                fout.write(blob)
            result = QResult(coord, None)
        except Exception as e:
            print(f"\nERR: {myname}:{type(e)}:{e}")
            result = QResult(coord, e)
        finally:
            shm.close()
            shm.unlink()
            result_queue.put(result)


async def aretrieve(in_queue: MP.Queue, out_queue: MP.Queue, disp_queue: MP.Queue, shm_allocator: SharedMemoryAllocator):
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(CONN_LIMIT * 3, client, cooked=False, cancel_flag=AbortRequested)

        def make_task(coord: CoordType):
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        tasks: set[asyncio.Task] = set()
        done: set[asyncio.Task]
        pending_tasks: set[asyncio.Task]
        job = in_queue.get()
        while True:
            if job is None:
                break
            if job is not Ellipsis:
                cmd, x, y  = cast(tuple[str, int, int], job)
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

                for fut in done:
                    fut_result = fut.result()
                    if fut_result is None:
                        continue
                    if not fut_result.result:
                        continue
                    out_queue.put(
                        {
                            "coord": fut_result.coord,
                            "tsf": datetime.strftime(datetime.now(), "%y%m%d-%H%M"),
                            "shm": shm_allocator.new(fut_result.coord, fut_result.result),
                        }
                    )

                tasks = pending_tasks

            if len(tasks) < 1050:
                try:
                    job = in_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(2)
                    job = Ellipsis
            else:
                job = Ellipsis


def retrieve(in_queue: MP.Queue, out_queue: MP.Queue, disp_queue: MP.Queue, shm_allocator: SharedMemoryAllocator):
    asyncio.run(aretrieve(in_queue, out_queue, disp_queue, shm_allocator))


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
        s_args = (
            Path(Config.maps.dir),
            save_queue,
            result_queue
        )

        outstanding: set[CoordType] = set()
        with MP.Pool(6, initializer=retrieve, initargs=r_args) as pool_r, MP.Pool(2, initializer=saver, initargs=s_args) as pool_s:
            for row in range(2100, -1, -1):
                coord_queue.put(("row", -1, row))
            tm: Optional[float] = None
            count: int = 0
            total: int = 0
            while not coord_queue.empty():
                if tm is None:
                    tm = time.monotonic()
                    count = 0
                try:
                    while True:
                        co = dispatched_queue.get(timeout=1)
                        outstanding.add(co)
                except queue.Empty:
                    pass
                try:
                    while True:
                        rslt: QResult = result_queue.get(timeout=1)
                        if rslt.exc is None:
                            outstanding.discard(rslt.coord)
                            count += 1
                            total += 1
                except queue.Empty:
                    pass
                elapsed = time.monotonic() - tm
                if elapsed >= 5.0:
                    rate = count / elapsed
                    print(f"{total:_} maptiles retrieved, at {rate:_.2f}rps", flush=True)



if __name__ == '__main__':
    main()
