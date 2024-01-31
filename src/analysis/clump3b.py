import pickle
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import ruamel.yaml

from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions

if TYPE_CHECKING:
    from sl_maptools import CoordType

Config: SLMapToolsConfig = ConfigReader("config.toml")

OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def main() -> None:  # noqa: D103
    regsdb = get_nonvoid_regions(Config.names)
    valid_coords: set[CoordType] = set(regsdb) & get_bonnie_coords(Config.bonnie)

    start = time.monotonic()

    work_queue: deque[CoordType]
    zones: list[set[CoordType]] = []
    zone: set[CoordType]
    while valid_coords:
        work_queue = deque([valid_coords.pop()])
        zone = set()
        while work_queue:
            coord = work_queue.popleft()
            zone.add(coord)
            x, y = coord
            for dx, dy in OFFSETS:
                dco = x + dx, y + dy
                if dco in zone:
                    continue
                if dco not in valid_coords:
                    continue
                valid_coords.remove(dco)
                zone.add(dco)
                work_queue.append(dco)
        if len(zone) > 1:
            zones.append(zone)

    finish = time.monotonic() - start
    print(f"Zoning took {finish:.2f} seconds")

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
