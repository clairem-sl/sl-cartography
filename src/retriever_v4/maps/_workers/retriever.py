# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import multiprocessing as MP
import queue
import signal
import sys
import time
from datetime import datetime
from multiprocessing import shared_memory as MPSharedMem
from typing import TYPE_CHECKING, Final, cast

import httpx

from retriever_v4.maps import QResult, QSaveJob
from sl_maptools import CoordType, MapCoord, SupportsSet
from sl_maptools.fetchers.map import BoundedMapFetcher

if TYPE_CHECKING:
    from collections.abc import Iterable


async def aretrieve(
    in_queue: MP.Queue,
    out_queue: MP.Queue,
    disp_queue: MP.Queue,
    result_queue: MP.Queue,
    abort_flag: SupportsSet,
) -> None:
    """Performs asynchronous retrieval of map tiles"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _half_cols = COLS_PER_ROW // 2
    _myname = MP.current_process().name
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedMapFetcher(CONN_LIMIT * 3, client, cooked=False, cancel_flag=abort_flag)

        def make_task(coord: CoordType) -> asyncio.Task:
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        tasks: set[asyncio.Task] = set()
        done: set[asyncio.Task]
        job: Ellipsis | tuple[str, CoordType | Iterable[CoordType] | int] = in_queue.get()
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
                done, tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
                disp_queue.put(len(done))

                for fut in done:
                    try:
                        exc = fut.exception()
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        exc = e
                    if exc is not None:
                        print(
                            f"{_myname}:{fut.get_name()} ERR <{type(exc)}>{exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                        _err = QResult(
                            f"{_myname}:{fut.get_name()}",
                            UNKNOWN_COORD,
                            cast(Exception, exc),
                        )
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
                        "tsf": datetime.now().astimezone().strftime("%y%m%d-%H%M"),
                        "shm": shm,
                    }
                    out_queue.put(save)
                    shm.close()

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
                print(f"{MP.current_process().name} idling 💤")
                time.sleep(1)

    print(f"{MP.current_process().name} done ⏹")


def retrieve(
    in_queue: MP.Queue,
    out_queue: MP.Queue,
    disp_queue: MP.Queue,
    retire_queue: MP.Queue,
    abort_flag: SupportsSet,
) -> None:
    """A worker that triggers the async retrieval of map tiles"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"Retriever-{num}"
    MP.current_process().name = myname
    asyncio.run(aretrieve(in_queue, out_queue, disp_queue, retire_queue, abort_flag))


UNKNOWN_COORD: Final[MapCoord] = MapCoord(-1, -1)
BATCH_WAIT: Final[int] = 1
CONN_LIMIT: Final[int] = 80
HTTP2: Final[bool] = True
COLS_PER_ROW: Final[int] = 2100
