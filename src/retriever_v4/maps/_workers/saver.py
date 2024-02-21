# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import multiprocessing as MP
import signal
import sys
import time
from typing import TYPE_CHECKING, cast

from retriever_v4.maps import QResult, QSaveJob

if TYPE_CHECKING:
    from pathlib import Path

    from sl_maptools import MapCoord


def saver(
    mapdir: Path,
    incoming_queue: MP.Queue,
    result_queue: MP.Queue,
) -> None:
    """A worker function that saves received map tiles"""
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
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"\nERR: {myname}:{type(e)}:{e}", file=sys.stderr, flush=True)
            result = QResult(myname, coord, e)
        result_queue.put(result)
