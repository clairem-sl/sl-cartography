# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import pickle
import re
import signal
import time
from datetime import datetime
from itertools import chain
from pathlib import Path

from typing import Protocol, cast

from PIL import Image

from sl_maptools import CoordType, AreaBounds, RegionsDBRecord, inventorize_maps_latest
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader
from sl_maptools.validator import get_bonnie_coords

Config = ConfigReader("config.toml")
AbortRequested: bool = False


def handle_sigint(_, __):
    global AbortRequested
    if AbortRequested:
        return
    AbortRequested = True


class CartographerOptions(Protocol):
    continents: list[str]
    areas: list[AreaBounds]
    mapdir: Path
    outdir: Path
    no_validate: bool
    regionsdb: Path
    overwrite: bool


class Options(CartographerOptions, Protocol):
    pass


RE_AREA = re.compile(r"(?P<x1>\d+)[,:-](?P<y1>\d+)[,:-](?P<x2>\d+)[,:-](?P<y2>\d+)")


class AreaParser(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        rslt = []
        for value in values:
            try:
                m = RE_AREA.match(value)
                x1 = int(m.group("x1"))
                y1 = int(m.group("y1"))
                x2 = int(m.group("x2"))
                y2 = int(m.group("y2"))
                if x2 < x1:
                    x1, x2 = x2, x1
                if y2 < y1:
                    y1, y2 = y2, y1
                rslt.append(AreaBounds(x1, y1, x2, y2))
            except AttributeError:
                parser.error(
                    f"Unrecognized area: '{value}' -- must be 'x1,y1-x2,y2' or 'x1,y1,x2,y2' "
                    f"where x and y values are integers"
                )
        setattr(namespace, self.dest, rslt)


def get_options() -> Options:
    parser = argparse.ArgumentParser("cartographer_v4")

    parser.add_argument(
        "--continents",
        type=str,
        nargs="*",
        help=(
            "Comma- or Space-separated list of area names to generate the maps for. "
            "If not specified and no 'areas' specified, then will generate all known areas/continents. "
            "If 'areas' are specified, then this will generate area maps in addition to the specified areas."
        ),
    )
    parser.add_argument(
        "areas",
        action=AreaParser,
        nargs="*",
        help=(
            "Optional area(s) to generate the map(s) for. Must be in the syntax x1,y1-x2,y2 "
            "where the x1, y1, x2, y2, are all integers. NOTE: If specified, will NOT generate "
            "other areas' maps, unless specified additionally with the --continents option. "
            "Conversely, if not specified, will generate maps of all known areas. "
            "Resulting map names will be 'x1-y1-x2-y2-timestamp.png'"
        ),
    )

    parser.add_argument(
        "--mapdir",
        type=Path,
        default=Config.maps.dir,
        help=(
            "Directory containing map tiles retrieved using retriever_v4.maps. "
            "Defaults to as specified in config.toml"
        ),
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        help="Directory to put the resulting hi-res maps in. Defaults to the same as --mapdir",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help=(
            "If specified, do not perform validation (against database of known regions and "
            "BonnieBots Regions DB). I.e, generate maps using all retrieved map tiles in the areas"
        ),
    )
    parser.add_argument(
        "--regionsdb",
        type=Path,
        default=Path(Config.names.dir) / Config.names.db,
        help="RegionsDB for validation. If not specified, use names.db in config.toml"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="If specified, overwrite existing hi-res map file."
    )

    _opts = parser.parse_args()
    if _opts.outdir is None:
        _opts.outdir = _opts.mapdir
    return cast(Options, _opts)


def make_map(targ: Path, bounds: AreaBounds, map_tiles: dict[CoordType, Path]):
    csize_x = (bounds.x_eastmost - bounds.x_westmost + 1) * 256
    csize_y = (bounds.y_northmost - bounds.y_southmost + 1) * 256
    canvas = Image.new("RGBA", (csize_x, csize_y))

    print(f"{bounds}", end="", flush=True)
    c = 0
    for y in bounds.y_iterator():
        for x in bounds.x_iterator():
            coord = (x, y)
            # print(coord)
            if coord not in map_tiles:
                continue
            c += 1
            if (c % 10) == 0:
                print(".", end="", flush=True)
            canv_x = (x - bounds.x_westmost) * 256
            canv_y = (bounds.y_northmost - y) * 256
            with Image.open(map_tiles[coord]) as img:
                img.load()
                canvas.paste(img, (canv_x, canv_y))

    # print(targ)
    canvas.save(targ)


def main(opts: Options):
    start = time.monotonic()

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    wanted_areas: list[tuple[str, AreaBounds]] = []
    if not opts.areas:
        if not opts.continents:
            wanted_areas.extend((name, area) for name, area in KNOWN_AREAS.items())
        else:
            for aa in chain(map(lambda s: s.split(","), opts.continents)):
                for a in aa:
                    wanted_areas.extend((a, KNOWN_AREAS[a]))
    else:
        for a in opts.areas:
            aname = f"{a.x_westmost}-{a.y_southmost}-{a.x_eastmost}-{a.y_northmost}-{ts}"
            wanted_areas.append((aname, a))
        if opts.continents:
            for aa in chain(map(lambda s: s.split(","), opts.continents)):
                for a in aa:
                    wanted_areas.extend((a, KNOWN_AREAS[a]))

    map_tiles = inventorize_maps_latest(opts.mapdir)

    if not opts.no_validate:
        validation_set: set[CoordType] = set()
        with opts.regionsdb.open("rb") as fin:
            regsdb: dict[CoordType, RegionsDBRecord] = pickle.load(fin)
        validation_set.update(k for k, v in regsdb.items() if v["current_name"])
        bonnie_coords = get_bonnie_coords(None, True)
        validation_set.intersection_update(bonnie_coords)
        for co in list(map_tiles.keys()):
            if co not in validation_set:
                del map_tiles[co]

    print("\nMaking maps:")
    opts.outdir.mkdir(exist_ok=True)
    orig_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_sigint)
    for area_name, area_bounds in wanted_areas:
        print(f"{area_name}: ", end="", flush=True)
        targ = opts.outdir / (area_name + ".png")
        if not opts.overwrite and targ.exists():
            print(f"Already exists", end="")
        else:
            make_map(targ, area_bounds, map_tiles)
        print(f"\n  => {targ}", flush=True)
        if AbortRequested:
            break
    signal.signal(signal.SIGINT, orig_sigint)

    finish = time.monotonic()
    print("=" * 40)
    print(f"Finished in {finish - start:_.2f} seconds.")


if __name__ == "__main__":
    options = get_options()
    main(options)
