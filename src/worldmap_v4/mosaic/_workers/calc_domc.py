#  This Source Code Form is subject to the terms of the Mozilla Public
#  License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
#  Copyright (C) 2023, Claire Morgenthau
from __future__ import annotations

import signal
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError

from sl_maptools.image_processing import FASCIA_SIZES, calculate_dominant_colors

if TYPE_CHECKING:
    import multiprocessing as MP
    from pathlib import Path

    from sl_maptools import CoordType
    from worldmap_v4.mosaic._workers import CalcResultType, DomColors

CollectorQueue: MP.Queue


@dataclass(eq=False, frozen=True, kw_only=True, slots=True)
class CalcDomcArgs:
    coll_queue: MP.Queue


def calc_domc_init(
    args: CalcDomcArgs,
) -> None:
    """Initializer for domc calculator workers"""
    global CollectorQueue  # noqa: PLW0603
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    CollectorQueue = args.coll_queue


def calc_domc(job: tuple[CoordType, Path]) -> CalcResultType | None:
    """A worker that calculates dominant color for a job"""
    coord, fpath = job
    if not fpath.exists() or not fpath.is_file():
        return None

    try:
        with Image.open(fpath) as img:
            img.load()
            domc: DomColors = {fsz: calculate_dominant_colors(img, fsz) for fsz in FASCIA_SIZES}
    except UnidentifiedImageError:
        fpath.unlink()
        return None

    rslt = coord, fpath, domc
    CollectorQueue.put(rslt)
    return rslt
