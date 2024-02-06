# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
import time
from collections import deque
from pathlib import Path
from typing import Protocol, cast, Generator

import ruamel.yaml

from sl_maptools import CoordType
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions


Config: SLMapToolsConfig = ConfigReader("config.toml")


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


def iter_neighbors(co: CoordType) -> Generator[CoordType, None, None]:
    """Iterates through all 4 neighbors of a coordinate"""
    x, y = co
    yield x - 1, y  # West
    yield x + 1, y  # East
    yield x, y - 1  # South
    yield x, y + 1  # North


def main(opts: Options) -> None:  # noqa: D103
    regsdb = get_nonvoid_regions(Config.names)
    valid_coords: set[CoordType] = set(regsdb) & get_bonnie_coords(Config.bonnie)

    start = time.monotonic()

    # A 'zone' is a set of coordinates that are ultimately traversable by travelling via adjacent regions
    # (not going diagonally, only N-E-W-S)
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
        if len(zone) > 1:
            zones.append(zone)
    del work_queue
    del valid_coords

    elapsed = time.monotonic() - start
    print(f"Zoning took {elapsed:.2f} seconds")

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
            for x, y in zone:
                rn = regsdb[x, y]["current_name"]
                minx = min(x, minx)
                maxx = max(x, maxx)
                miny = min(y, miny)
                maxy = max(y, maxy)
                prefx = f"{i:2}) ({x},{y}) {rn}"
                if arealist := regareas.get(rn):
                    areas.update(arealist)
                    if opts.all:
                        print(prefx, f"[{'; '.join(arealist)}]")
                else:
                    print(prefx, "### None")
            print("-" * 10, end=" ")
            bounds = [str(minx)]
            if maxx != minx:
                bounds.append(f"-{maxx}")
            bounds.append(f"/{miny}")
            if maxy != miny:
                bounds.append(f"-{maxy}")
            print("".join(bounds), end="")
            if areas:
                print(" =>", "; ".join(sorted(areas)))
            else:
                print()


if __name__ == "__main__":
    main(get_options())
