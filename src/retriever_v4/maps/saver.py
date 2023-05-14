# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import io
import multiprocessing as MP
import signal
import time
from dataclasses import dataclass
from multiprocessing import shared_memory as MPSharedMem
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
from PIL import Image
from skimage.metrics import mean_squared_error as mse
from skimage.metrics import structural_similarity as ssim

from retriever_v4 import DebugLevel
from sl_maptools import CoordType, MapCoord


@dataclass
class Thresholds:
    MSE: float
    SSIM: float


class QJob(TypedDict):
    coord: MapCoord
    tsf: str
    shm: MPSharedMem.SharedMemory


def saver(
    mapdir: Path,
    map_inventory: dict[CoordType, list[Path]],
    save_queue: MP.Queue,
    success_queue: MP.Queue,
    saved_coords: dict[CoordType, None],
    worker_state: dict[str, tuple[str, str | None]],
    debug_level: DebugLevel,
    thresholds: Thresholds,
    possibly_changed: dict[CoordType, None],
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    mapdir.mkdir(parents=True, exist_ok=True)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"SaverWorker-{num}"
    MP.current_process().name = myname
    targf: Path | None = None
    counter: int = 0

    def _setstate(state: str, with_targ: bool = True):
        if with_targ and targf:
            worker_state[myname] = state, targf.name
        else:
            worker_state[myname] = state, None

    def _pip(char: str):
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
            try:
                tsf = regmap["tsf"]
                targf = mapdir / f"{coord.x}-{coord.y}_{tsf}.jpg"
                _setstate("saving")
                with targf.open("wb") as fout:
                    fout.write(blob)
            except Exception:
                raise

            saved_coords[coord] = None
            counter = len(saved_coords)
            _pip("💾")

            _setstate("decoding")
            with io.BytesIO(blob) as bio:
                img: Image.Image = Image.open(bio)
                img.load()

            # Prune older file of same coordinate if really similar
            if (coordfiles := map_inventory.get(coord)) is None:
                continue
            _setstate("converting1")
            # noinspection PyTypeChecker
            f1_arr = np.asarray(img.convert("L"))
            f2_img: Image.Image | None = None
            do_delete: bool = False
            while coordfiles:
                f2 = coordfiles[-1]
                try:
                    _setstate("fetching")
                    with f2.open("rb") as fin:
                        f2_img = Image.open(fin)
                        f2_img.load()
                    _setstate("converting2")
                    # noinspection PyTypeChecker
                    f2_arr = np.asarray(f2_img.convert("L"))
                    # Image similarity test using Structural Similarity Index,
                    # see https://pyimagesearch.com/2014/09/15/python-compare-two-images/
                    _setstate("comparing_mse")
                    mse_result = mse(f1_arr, f2_arr)
                    if mse_result < thresholds.MSE:
                        do_delete = True
                        _setstate("deleting_mse")
                    else:
                        _setstate("comparing_ssim")
                        ssim_result = ssim(f1_arr, f2_arr)
                        if ssim_result > thresholds.SSIM:
                            do_delete = True
                            _setstate("deleting_ssim")
                    if do_delete:
                        f2.unlink()
                        coordfiles.pop()
                        _pip("❌")
                        do_delete = False
                    else:
                        possibly_changed[coord] = None
                        break
                except FileNotFoundError:
                    if coordfiles:
                        coordfiles.pop()
                except Exception as e:
                    print(f"\nERR: {myname}:{type(e)}:{e}")
                    raise
                finally:
                    if f2_img is not None:
                        f2_img.close()
            _setstate("resolving")
            coordfiles.append(targf)
            map_inventory[coord] = coordfiles
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