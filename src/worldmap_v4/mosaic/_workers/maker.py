#  This Source Code Form is subject to the terms of the Mozilla Public
#  License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
#  Copyright (C) 2023, Claire Morgenthau
from __future__ import annotations

import multiprocessing as MP
import signal
from collections.abc import MutableMapping
from pathlib import Path
from typing import Final, NamedTuple

from PIL import Image

from sl_maptools import CoordType
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.image_processing import RGBTuple
from sl_maptools.utils import make_pnginfo

FASCIA_PIXELS: Final[dict[int, int]] = {
    1: 3,
    2: 3,
    3: 3,
    4: 2,
    5: 2,
}


class MakerParams(NamedTuple):
    """Parameters passed to the make_mosaic worker"""

    worker_state: MutableMapping[str, str]
    queue: MP.Queue
    patches_coll: MutableMapping[tuple[CoordType, int], list[RGBTuple]]
    coll_lock: MP.RLock
    outdir: Path


def make_mosaic(params: MakerParams) -> None:
    """
    Gather dominant colors and create the mosaic maps.
    You shouldn't launch too many of this worker, since this worker is not the bottleneck.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    def _state(state: str) -> None:
        params.worker_state["maker"] = state

    while True:
        _state("idle")
        item = params.queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        if not isinstance(item, tuple):
            continue

        _state("got_job")
        assert isinstance(item, tuple)
        patches_bysz: dict[int, dict[CoordType, list[RGBTuple]]] = {sz: {} for sz in item}
        with params.coll_lock:
            _state("transform")
            for k, v in dict(params.patches_coll).items():
                coord, sz = k
                if sz not in patches_bysz:
                    continue
                patches_bysz[sz][coord] = v

        for sz, patches in patches_bysz.items():
            _state(f"make_{sz}_canvas")
            print(f"⏺{sz}", end="", flush=True)
            fpx = FASCIA_PIXELS[sz]
            fbox = fpx, fpx
            tsz = fpx * sz
            sidelen = 2101 * tsz
            canvas = Image.new("RGBA", (sidelen, sidelen))
            _state(f"make_{sz}_patches")
            for coord, colors in patches.items():
                x, y = coord
                cx = tsz * x
                cy = tsz * (2100 - y)
                sx = sy = 0
                for col in colors:
                    canvas.paste(Image.new("RGB", fbox, color=col), (cx + sx, cy + sy))
                    sy += fpx
                    if sy >= tsz:
                        sy = 0
                        sx += fpx
            _state(f"save_{sz}")
            metadata = make_pnginfo(
                title=f"Second Life Mosaic Worldmap {sz}x{sz}",
                description=(
                    f"Mosaic Worldmap of Second Life, each region reduced to {sz}x{sz} tiles representing "
                    f"the region's dominant colors"
                ),
                info=Config.info,
            )
            targ = params.outdir / f"worldmap4_mosaic_{sz}x{sz}.png"
            canvas.save(targ, optimize=True, pnginfo=metadata)
            canvas.close()
            print(f"💾{sz}", end="", flush=True)

        # Release references to help GC
        del canvas
        del patches_bysz

    _state("ended")
