import argparse
import pickle
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import ruamel.yaml

from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions

if TYPE_CHECKING:
    from sl_maptools import CoordType

Config: SLMapToolsConfig = ConfigReader("config.toml")

OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


class Options(Protocol):
    """Represents options extracted from CLI"""

    all: bool
    no_save: bool


def get_options() -> Options:
    """Extract options from CLI"""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--all", action="store_true", default=False, help="Show all regions, not just those not associated with an area"
    )
    parser.add_argument("--no-save", action="store_true", default=False)

    return cast(Options, parser.parse_args())


def main(opts: Options) -> None:  # noqa: D103
    regsdb = get_nonvoid_regions(Config.names)
    valid_coords: set[CoordType] = set(regsdb) & get_bonnie_coords(Config.bonnie)

    start = time.monotonic()

    work_queue = deque([])
    zones: list[set[CoordType]] = []
    zone: set[CoordType]
    while valid_coords:
        zone = {coord := valid_coords.pop()}
        while True:
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
            if not work_queue:
                break
            coord = work_queue.popleft()
        if len(zone) > 1:
            zones.append(zone)
    del work_queue
    del valid_coords

    finish = time.monotonic() - start
    print(f"Zoning took {finish:.2f} seconds")

    len_zones: dict[int, list[set[CoordType]]] = {}
    for zone in zones:
        len_zones.setdefault(len(zone), []).append(zone)

    for num in sorted(len_zones):
        print(f"Clump of size {num} = {len(len_zones[num])} zones")

    if not opts.no_save:
        clumpsdb_p = Path(Config.names.dir) / "clumps.pkl"
        with clumpsdb_p.open("wb") as fout:
            pickle.dump(len_zones, fout)
        print(f"Saved to {clumpsdb_p}")
    else:
        print("Not saved because --no-save is specified")

    regions_areas = Path(Config.areas.dir) / "regions_areas.yaml"
    yaml = ruamel.yaml.YAML(typ="safe")
    with regions_areas.open("rt") as fin:
        regareas = yaml.load(fin)

    lenssc = [f"{k} ({len(v)})" for k, v in sorted(len_zones.items())]
    while True:
        print("\nAvailable lens:", ", ".join(lenssc))
        inp = input("Len (0 to end) ? ")
        try:
            inp = int(inp)
        except ValueError:
            print(f"Invalid input: {inp}")
            continue
        if inp == 0:
            break
        if inp not in len_zones:
            print(f"\nNo clumps of size {inp}")
            continue

        for i, zone in enumerate(len_zones[inp], start=1):
            print()
            minx = miny = 9999
            maxx = maxy = -1
            areas: set[str] = set()
            for co in zone:
                rn = regsdb[co]["current_name"]
                minx = min(co[0], minx)
                maxx = max(co[0], maxx)
                miny = min(co[1], miny)
                maxy = max(co[1], maxy)
                prefx = f"{i:2}) {co} {rn}"
                if arealist := regareas.get(rn):
                    areas.update(arealist)
                    if opts.all:
                        print(prefx, f"[in {', '.join(arealist)}]")
                else:
                    print(prefx, "### None")
            print("-" * 10, end=" ")
            bounds = [str(minx)]
            if maxx != minx:
                bounds.append(f"-{maxx}")
            bounds.append(f"/{miny}")
            if maxy != miny:
                bounds.append(f"-{maxy}")
            print("".join(bounds), " ".join(sorted(areas)))


if __name__ == "__main__":
    main(get_options())