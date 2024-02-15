#  This Source Code Form is subject to the terms of the Mozilla Public
#  License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
#  Copyright (C) 2023, Claire Morgenthau
from __future__ import annotations

import multiprocessing as MP
import signal
from dataclasses import dataclass
from typing import cast, MutableMapping

from sl_maptools import CoordType
from sl_maptools.image_processing import RGBTuple
from worldmap_v4.mosaic._workers import CalcResultType


@dataclass(eq=False, frozen=True, kw_only=True, slots=True)
class CollectorArgs:
    coll_queue: MP.Queue
    patches_coll: MutableMapping[tuple[CoordType, int], list[RGBTuple]]
    coll_lock: MP.RLock


def collector(
    args: CollectorArgs,
) -> None:
    """Gather results of domc calculation into a collection"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        item = args.coll_queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        coord, _, domc = cast(CalcResultType, item)
        with args.coll_lock:
            for sz, colors in domc.items():
                args.patches_coll[coord, sz] = colors
