import pickle
from pathlib import Path
from typing import TYPE_CHECKING

import ruamel.yaml

if TYPE_CHECKING:
    from sl_maptools import CoordType
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions

Config: SLMapToolsConfig = ConfigReader("config.toml")

OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def main() -> None:  # noqa: D103
    regsdb = get_nonvoid_regions(Config.names)
    valid_coords: set[CoordType] = set(regsdb) & get_bonnie_coords(Config.bonnie)

    # Make a list of "zones", i.e., coordinates with adjancies
    zones: list[set[CoordType]] = []
    for co in valid_coords:
        curzone: set[CoordType] = {co}
        x, y = co
        for dx, dy in OFFSETS:
            tco = x + dx, y + dy
            if tco in valid_coords:
                curzone.add(tco)
        if len(curzone) > 1:
            zones.append(curzone)

    # Combine adjacent zones into clumps
    # How this works:
    #  - Get one zone from working list
    #  - For the rest of the zones
    #    - If intersects, combine the zones
    #    - If not, add the zone into a "left out" list
    #  - Record the enlarged zone (might also be still same size)
    #  - Replace working list with the "left out" list
    #  - Repeat until no changes

    combos: list[set[CoordType]]
    left_out: list[set[CoordType]]
    prev_len: int = 0
    while prev_len != len(zones):
        prev_len = len(zones)
        print(prev_len, flush=True)
        combos = []
        while zones:
            curzone: set[CoordType] = zones.pop()
            left_out = []
            for one in zones:
                if curzone.intersection(one):
                    curzone.update(one)
                else:
                    left_out.append(one)
            combos.append(curzone)
            zones = left_out
        zones = combos

    len_zones: dict[int, list[set[CoordType]]] = {}
    for zone in zones:
        len_zones.setdefault(len(zone), []).append(zone)

    for num in sorted(len_zones):
        print(f"Clump of size {num} = {len(len_zones[num])} zones")

    clumpsdb_p = Path(Config.names.dir) / "clumps.pkl"
    with clumpsdb_p.open("wb") as fout:
        pickle.dump(len_zones, fout)
    print(f"Saved to {clumpsdb_p}")

    regions_areas = Path(Config.areas.dir) / "regions_areas.yaml"
    yaml = ruamel.yaml.YAML(typ="safe")
    with regions_areas.open("rt") as fin:
        regareas = yaml.load(fin)

    lenss = sorted(len_zones)
    while True:
        print("Available lens:", lenss)
        try:
            inp = int(input("Len (0 to end) ? "))
        except ValueError:
            inp = 0
        if inp == 0:
            break

        for i, zone in enumerate(len_zones[inp], start=1):
            for co in zone:
                rn = regsdb[co]["current_name"]
                print(f"{i:2}) {co} {rn}", end=" ")
                if arealist := regareas.get(rn):
                    print(f"[in {', '.join(arealist)}]")
                else:
                    print()
            print("-" * 10)


if __name__ == "__main__":
    main()
