# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import multiprocessing as MP
import signal
import time
from multiprocessing import shared_memory as MPSharedMem
from typing import TYPE_CHECKING, TypedDict, cast

from retriever_v4 import DebugLevel
from sl_maptools import CoordType

if TYPE_CHECKING:
    from pathlib import Path

    from PIL import Image

    from sl_maptools import MapCoord


class QJob(TypedDict):
    """Represents a queued job"""

    coord: MapCoord
    tsf: str
    shm: MPSharedMem.SharedMemory


def saver(
    mapdir: Path,
    save_queue: MP.Queue,
    success_queue: MP.Queue,
    saved_coords: dict[CoordType, None],
    worker_state: dict[str, tuple[str, str | None]],
    debug_level: DebugLevel,
) -> None:
    """A worker that saves map tile to file"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    mapdir.mkdir(parents=True, exist_ok=True)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"SaverWorker-{num}"
    MP.current_process().name = myname
    targf: Path | None = None
    counter: int = 0

    def _setstate(state: str, with_targ: bool = True) -> None:
        if with_targ and targf:
            worker_state[myname] = state, targf.name
        else:
            worker_state[myname] = state, None

    def _pip(char: str) -> None:
        if debug_level > DebugLevel.DISABLED:
            print(char, end="", flush=True)
            if debug_level >= DebugLevel.DETAILED:
                print(f"[{counter}]", end="", flush=True)

    img: Image.Image | None = None
    while True:
        _setstate("idle", False)
        if save_queue.empty():
            time.sleep(1)
            continue
        item = save_queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        _setstate("got_job", False)
        regmap: QJob = cast(QJob, item)
        coord: MapCoord = regmap["coord"]
        shm: MPSharedMem.SharedMemory = regmap["shm"]
        if coord in saved_coords:
            shm.close()
            continue
        blob = cast(bytes, shm.buf)
        try:
            tsf = regmap["tsf"]
            targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
            _setstate("saving")
            with targf.open("wb") as fout:
                fout.write(blob)

            saved_coords[cast(CoordType, coord)] = None
            counter = len(saved_coords)
            _pip("💾")
            success_queue.put(coord)
        except Exception as e:
            print(f"\nERR: {myname}:{type(e)}:{e}")
            raise
        finally:
            _setstate("cleaning")
            shm.close()
            if img is not None:
                img.close()
    _setstate("ended")
