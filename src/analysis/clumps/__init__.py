# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from collections import deque
from typing import Generator

from sl_maptools import CoordType


def iter_neighbors(co: CoordType) -> Generator[CoordType, None, None]:
    """Iterates through all 4 adjacent neighbors of a coordinate"""
    x, y = co
    yield x - 1, y  # West
    yield x + 1, y  # East
    yield x, y - 1  # South
    yield x, y + 1  # North


def get_clumps(coords: set[CoordType], *, skip_singles: bool = True) -> list[set[CoordType]]:
    """
    Returns a list of found zones.
    A 'zone' is a set of coordinates that are ultimately traversable by travelling via adjacent regions
    ('adjacent' means not going diagonally, only N-E-W-S)

    :param coords: Set of coordinates to scan over.
                   This will be shallow-copied first so original set will not be modified
    :param skip_singles: If True (default), do not add zones of single members to the result
    """
    valid_coords = coords.copy()

    work_queue = deque([])
    zones: list[set[CoordType]] = []
    zone: set[CoordType]

    while valid_coords:
        zone = {coord := valid_coords.pop()}
        while True:
            for dco in iter_neighbors(coord):
                if dco in zone:
                    continue
                if dco not in valid_coords:
                    continue
                valid_coords.remove(dco)
                zone.add(dco)
                work_queue.append(dco)
            if not work_queue:
                break
            coord = work_queue.popleft()
        if not skip_singles or len(zone) > 1:
            zones.append(zone)

    return zones
