import pickle
from collections import deque
from pathlib import Path
from typing import Final

from sl_maptools import AreaBounds, CoordType, RegionsDBRecord
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader
from sl_maptools.validator import get_bonnie_coords, inventorize_maps_latest

INTERESTING_CLUMPSIZE_THRESHOLD: Final[int] = 10


Config = ConfigReader("config.toml")


def main():
    map_tiles = inventorize_maps_latest(Config.maps.dir)
    regionsdb = Path(Config.names.dir) / Config.names.db

    validation_set: set[CoordType] = set()
    with regionsdb.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord] = pickle.load(fin)
    validation_set.update(k for k, v in regsdb.items() if v["current_name"])
    bonnie_coords = get_bonnie_coords(None, True)
    # print(bonnie_coords)
    validation_set.intersection_update(bonnie_coords)
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
    unassigned_clumps: list[set[CoordType]] = [c for c in list_of_clumps]
    perarea_clumps_of_interest: dict[str, list[set[CoordType]]] = {}
    for aname, abounds in KNOWN_AREAS.items():
        acoords: set[CoordType] = {xy for xy in abounds.xy_iterator()}
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
        _coords: set[CoordType] = {xy for xy in abounds.xy_iterator()}
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

    for info in interesting_clumps:
        aname, clump, reason = info
        if len(clump) >= 10:
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
                for coord in sorted(clump, key=lambda co: regsdb[co]["current_name"]):
                    print(coord, regsdb[coord]["current_name"])
                print(f"{AreaBounds.from_coordset(clump)=}")


if __name__ == "__main__":
    main()
