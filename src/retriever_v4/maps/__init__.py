# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, TypedDict

if TYPE_CHECKING:
    from multiprocessing import shared_memory as MPSharedMem

    from sl_maptools import MapCoord


class QResult(NamedTuple):
    """Represents a Result job"""

    entity: str
    coord: MapCoord
    exc: Exception | None


class QSaveJob(TypedDict):
    """Represents a Save job"""

    coord: MapCoord
    tsf: str
    shm: MPSharedMem.SharedMemory
