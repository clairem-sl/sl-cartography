import pickle
from collections import deque
from pathlib import Path
from pprint import pprint

from sl_maptools import inventorize_maps_latest, CoordType, RegionsDBRecord, AreaBounds
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader
from sl_maptools.validator import get_bonnie_coords

Config = ConfigReader("config.toml")


def main():
    map_tiles = inventorize_maps_latest(Config.maps.dir)
    regionsdb = Path(Config.names.dir) / Config.names.db

    validation_set: set[CoordType] = set()
    with regionsdb.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord] = pickle.load(fin)
    validation_set.update(k for k, v in regsdb.items() if v["current_name"])
    bonnie_coords = get_bonnie_coords(None, True)
    print()
    validation_set.intersection_update(bonnie_coords)
    for co in list(map_tiles.keys()):
        if co not in validation_set:
            del map_tiles[co]

    all_coords = set(map_tiles.keys())
    unprocesseds = all_coords.copy()

    def alone(co: CoordType):
        x, y = co
        neighbors = {(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)}
        return not bool(neighbors.intersection(all_coords))

    def get_clump(start: CoordType):
        clump = set()
        q: deque[tuple[int, int]] = deque()
        q.append(start)
        while q:
            n = q.popleft()
            if n in clump:
                continue
            if n in all_coords:
                clump.add(n)
                x, y = n
                q.append((x - 1, y))
                q.append((x + 1, y))
                q.append((x, y - 1))
                q.append((x, y + 1))
        return clump
        # if start not in all_coords:
        #     return clump
        # x, y = start
        # s: deque[tuple[int, int, int, int]] = deque()
        # s.append((x, x, y, 1))
        # s.append((x, x, y-1, -1))
        # while s:
        #     x1, x2, y, dy = s.popleft()
        #     x = x1
        #     if (x, y) in all_coords:
        #         while (x - 1, y) in all_coords:
        #             clump.add((x - 1, y))
        #             x -= 1
        #     if x < x1:
        #         s.append((x, x1-1, y-dy, -dy))
        #     while x1 <= x2:
        #         while (x1, y) in all_coords:
        #             clump.add((x1, y))
        #             x1 = x1 + 1
        #             s.append((x, x1 - 1, y+dy, dy))
        #             if (x1 - 1) > x2:
        #                 s.append((x2 + 1, x1 - 1, y-dy, -dy))
        #         x1 += 1
        #         while x1 < x2 and (x1, y) not in all_coords:
        #             x1 += 1
        #         x = x1
        #     pprint(s)
        # return clump

    clumps: list[set[CoordType]] = []
    for y in range(2100, -1, -1):
        # print(f"ROW:{y}", flush=True)
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
        known_coords[aname] = {
            coord
            for coord in abounds.xy_iterator()
            if coord in all_coords
        }

    new_clup: list[set[CoordType]] = []
    for clump in clumps:
        l = len(clump)
        if l < 15:
            continue
        print(l, sorted(clump, key=lambda i: (i[1], i[0]))[0:5], "...")
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
        interesting[f"Interesting-{i}"] = AreaBounds(min(xs), min(ys), max(xs), max(ys))
    pprint(interesting)


if __name__ == '__main__':
    main()
