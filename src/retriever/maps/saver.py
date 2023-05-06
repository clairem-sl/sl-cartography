from __future__ import annotations

import io
import multiprocessing as MP
import signal
import time
from dataclasses import dataclass
from multiprocessing import shared_memory as MPSharedMem
from pathlib import Path
from typing import Any, cast, TypedDict

import numpy as np
from PIL import Image
from skimage.metrics import mean_squared_error as mse, structural_similarity as ssim

from retriever import DebugLevel
from sl_maptools import MapCoord


@dataclass
class Thresholds:
    MSE: float
    SSIM: float


def saver(
    mapdir: Path,
    mapfilesets: dict[tuple[int, int], list[Path]],
    save_queue: MP.Queue,
    success_queue: MP.Queue,
    saved: dict[MapCoord, Any],
    worker_state: dict[str, tuple[str, str | None]],
    debug_level: DebugLevel,
    thresholds: Thresholds,
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    mapdir.mkdir(parents=True, exist_ok=True)
    curname = MP.current_process().name
    _, num = curname.split("-")
    myname = f"SaverWorker-{num}"
    MP.current_process().name = myname
    targf: Path | None = None

    def _setstate(state: str, with_targ: bool = True):
        if with_targ and targf:
            worker_state[myname] = state, targf.name
        else:
            worker_state[myname] = state, None

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
        if coord in saved:
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

            saved[coord] = None
            counter = len(saved)
            if debug_level > DebugLevel.DISABLED:
                print(f"💾", end="", flush=True)
                if debug_level >= DebugLevel.DETAILED:
                    print(f"[{counter}]", end="", flush=True)

            _setstate("decoding")
            with io.BytesIO(blob) as bio:
                img: Image.Image = Image.open(bio)
                img.load()

            # if dominant_colors is not None:
            #     domc: dict[int, list[RGBTuple]] = {}
            #     for fasz in FASCIA_COORDS:
            #         domc[fasz] = calculate_dominant_colors(img, fasz)
            #     dominant_colors[tuple(coord)] = domc

            # Prune older file of same coordinate if really similar
            if (coordfiles := mapfilesets.get(coord)) is None:
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
                        if debug_level > DebugLevel.DISABLED:
                            print(f"❌", end="", flush=True)
                            if debug_level >= DebugLevel.DETAILED:
                                print(f"[{counter}]", end="", flush=True)
                        do_delete = False
                    else:
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
            mapfilesets[coord] = coordfiles
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


class QJob(TypedDict):
    coord: MapCoord
    tsf: str
    shm: MPSharedMem.SharedMemory
