# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from collections import deque
from pprint import pprint
from typing import Final

from sl_maptools import AreaBounds, CoordType
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader
from sl_maptools.validator import (
    get_bonnie_coords,
    get_nonvoid_regions,
    inventorize_maps_latest,
)

INTERESTING_CLUMPSIZE_THRESHOLD: Final[int] = 10


Config = ConfigReader("config.toml")


def main():
    map_tiles = inventorize_maps_latest(Config.maps.dir)

    validation_set = set(get_nonvoid_regions(Config.names)) & get_bonnie_coords(Config.bonnie)
    for co in list(map_tiles.keys()):
        if co not in validation_set:
            del map_tiles[co]

    all_coords = set(map_tiles.keys())
    unprocesseds = all_coords.copy()

    def alone(_co: CoordType):
        _x, _y = _co
        neighbors = {(_x - 1, _y), (_x + 1, _y), (_x, _y - 1), (_x, _y + 1)}
        return not bool(neighbors.intersection(all_coords))

    def get_clump(start: CoordType):
        _clump = set()
        q: deque[tuple[int, int]] = deque()
        q.append(start)
        while q:
            n = q.popleft()
            if n in _clump:
                continue
            if n in all_coords:
                _clump.add(n)
                _x, _y = n
                q.append((_x - 1, _y))
                q.append((_x + 1, _y))
                q.append((_x, _y - 1))
                q.append((_x, _y + 1))
        return _clump

    clumps: list[set[CoordType]] = []
    for y in range(2100, -1, -1):
        for x in range(0, 2101):
            if (x, y) not in unprocesseds:
                continue
            coord = x, y
            unprocesseds.discard(coord)
            if alone(coord):
                continue
            # print(len(unprocesseds), coord)
            clump = get_clump(coord)
            unprocesseds.difference_update(clump)
            clumps.append(clump)

    known_coords: dict[str, set[CoordType]] = {}
    for aname, abounds in KNOWN_AREAS.items():
        known_coords[aname] = {coord for coord in abounds.xy_iterator() if coord in all_coords}

    new_clup: list[set[CoordType]] = []
    for clump in clumps:
        clumplen = len(clump)
        if clumplen < INTERESTING_CLUMPSIZE_THRESHOLD:
            continue
        print(clumplen, sorted(clump, key=lambda _i: (_i[1], _i[0]))[0:5], "...")
        found = False
        for aname, coords in known_coords.items():
            cl_i_co = clump.intersection(coords)
            if not cl_i_co:
                continue
            if cl_i_co == clump:
                print(f"  part of {aname}")
                found = True
            elif cl_i_co == coords:
                print(f"  {aname} part of")
                found = True
            else:
                print(f"  intersected {aname}")
                found = True
        if not found:
            print("  New Clump!")
            new_clup.append(clump)

    interesting: dict[str, AreaBounds] = {}
    for i, clump in enumerate(new_clup, start=1):
        xs = []
        ys = []
        for coord in clump:
            xs.append(coord[0])
            ys.append(coord[1])
        interesting[f"Interesting-{i:03}"] = AreaBounds(min(xs), min(ys), max(xs), max(ys))
    pprint(interesting)


if __name__ == "__main__":
    main()
