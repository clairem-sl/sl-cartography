# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
from collections import deque
from typing import Final, Protocol, cast

from sl_maptools import AreaBounds, CoordType, inventorize_maps_latest
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.knowns import DO_NOT_MAP_AREAS, KNOWN_AREAS
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions

INTERESTING_CLUMPSIZE_THRESHOLD: Final[int] = 10


class Options(Protocol):
    min_clumpsize: int


def _get_options() -> Options:
    parser = argparse.ArgumentParser("analysis.clump2")
    parser.add_argument("--min-clumpsize", type=int, default=INTERESTING_CLUMPSIZE_THRESHOLD)

    _opts = parser.parse_args()
    return cast(Options, _opts)


def main(opts: Options):
    map_tiles = inventorize_maps_latest(Config.maps.dir)

    regsdb = get_nonvoid_regions(Config.names)
    validation_set = set(regsdb) & get_bonnie_coords(Config.bonnie)
    for co in list(map_tiles.keys()):
        if co not in validation_set:
            del map_tiles[co]

    # all_coords = set(map_tiles.keys())
    all_coords = validation_set
    unprocesseds = all_coords.copy()
    # print(unprocesseds)

    def alone(_co: CoordType, valid_set: set[CoordType]):
        _x, _y = _co
        neighbors = {(_x - 1, _y), (_x + 1, _y), (_x, _y - 1), (_x, _y + 1)}
        return not bool(neighbors.intersection(valid_set))

    def get_clump(start: CoordType, valid_set: set[CoordType]):
        # This uses Flood Fill algo from this article:
        # https://en.wikipedia.org/wiki/Flood_fill#Moving_the_recursion_into_a_data_structure
        # For our purposes the performance is Good Enough.
        # (I can't get the more advanced "span filling" algo to work)
        _clump = set()
        q: deque[tuple[int, int]] = deque()
        q.append(start)
        while q:
            n = q.popleft()
            if n in _clump or n not in valid_set:
                continue
            _clump.add(n)
            _x, _y = n
            q.append((_x - 1, _y))
            q.append((_x + 1, _y))
            q.append((_x, _y - 1))
            q.append((_x, _y + 1))
        return _clump

    # First, we find all the clumps
    list_of_clumps: list[set[CoordType]] = []
    for y in range(2100, -1, -1):
        for x in range(0, 2101):
            if (x, y) not in unprocesseds:
                continue
            coord = x, y
            unprocesseds.discard(coord)
            if alone(coord, all_coords):
                continue
            # print(len(unprocesseds), coord)
            clump = get_clump(coord, all_coords)
            unprocesseds.difference_update(clump)
            list_of_clumps.append(clump)
    # print(list_of_clumps)

    # Now, let's find per-area "clumps of interest"
    unassigned_clumps: list[set[CoordType]] = list(list_of_clumps)
    perarea_clumps_of_interest: dict[str, list[set[CoordType]]] = {}
    for aname, abounds in KNOWN_AREAS.items():
        acoords: set[CoordType] = set(abounds.xy_iterator())
        for clump in list_of_clumps:
            if clump not in unassigned_clumps:
                continue
            if acoords.intersection(clump):
                perarea_clumps_of_interest.setdefault(aname, []).append(clump)
                unassigned_clumps.remove(clump)
    # print(perarea_clumps_of_interest)
    # at this point, unassigned_clumps are 'new' clumps outside any area bounds
    interesting_clumps: list[tuple[str, set[CoordType], str]] = [("", cl, "new") for cl in unassigned_clumps]

    # Next, let's find per-area "existing clumps"
    perarea_existing_clumps: dict[str, list[set[CoordType]]] = {}
    perarea_existing_coords: dict[str, set[CoordType]] = {}
    for aname, abounds in KNOWN_AREAS.items():
        _coords: set[CoordType] = set(abounds.xy_iterator())
        _unprocs = _coords.copy()
        while _unprocs:
            _co = _unprocs.pop()
            perarea_existing_coords.setdefault(aname, set()).add(_co)
            if alone(_co, _coords):
                continue
            _clu = get_clump(_co, _coords)
            perarea_existing_coords.setdefault(aname, set()).update(_clu)
            _unprocs.difference_update(_clu)
            perarea_existing_clumps.setdefault(aname, []).append(_clu)

    for aname, aclumps in perarea_existing_clumps.items():
        # print(aname)
        if aname not in perarea_clumps_of_interest:
            continue
        # print(aname)
        for clump in perarea_clumps_of_interest[aname]:
            for a_1clump in aclumps:
                intersect = a_1clump.intersection(clump)
                if not intersect:
                    continue
                if clump == a_1clump:
                    # Found but still the same
                    break
                if intersect == clump:
                    # a_1clump is bigger
                    interesting_clumps.append((aname, clump, "shrunk"))
                elif intersect == a_1clump:
                    # clump is bigger
                    interesting_clumps.append((aname, clump, "grew"))
                else:
                    interesting_clumps.append((aname, clump, "mutated"))
                break
            else:
                # We enter here only if 'break' not invoked
                interesting_clumps.append((aname, clump, "new"))
                continue

    # Finally, let's do some blacklisting
    do_not_check_coords: set[CoordType] = set()
    for abounds in DO_NOT_MAP_AREAS.values():
        _coords: set[CoordType] = set(abounds.xy_iterator())
        _coords.intersection_update(all_coords)
        do_not_check_coords.update(_coords)
    clumps_to_check: list[tuple[str, set[CoordType], str]] = []
    for aname, clump, reason in interesting_clumps:
        if clump.intersection(do_not_check_coords):
            continue
        clumps_to_check.append((aname, clump, reason))

    for info in clumps_to_check:
        aname, clump, reason = info
        if len(clump) >= opts.min_clumpsize:
            if aname:
                continue
                # if reason == "grew":
                #     diff = clump - perarea_existing_coords[aname]
                #     print(f"{aname} adds: {diff}")
                # elif reason == "shrunk":
                #     diff = perarea_existing_coords[aname] - clump
                #     print(f"{aname} lost: {diff}")
                # elif reason == "mutated":
                #     intersect = clump.intersection(perarea_existing_coords[aname])
                #     diff = (clump - intersect) | (perarea_existing_coords[aname] - intersect)
                #     print(f"{aname} mutated: {diff}")
            else:
                print(f"NEW: {len(clump)} {clump}")
                for coord in sorted(clump, key=lambda c: regsdb[c]["current_name"]):
                    print(" ", coord, regsdb[coord]["current_name"])
                print(f"    => {AreaBounds.from_coordset(clump)=}")

    print("===== Requested Areas =====")
    for clump in list_of_clumps:
        if (698, 1132) in clump:
            print(f"NEW: {len(clump)} {clump}")
            for coord in sorted(clump, key=lambda c: regsdb[c]["current_name"]):
                print(" ", coord, regsdb[coord]["current_name"])
            print(f"    => {AreaBounds.from_coordset(clump)=}")


if __name__ == "__main__":
    options = _get_options()
    main(options)
