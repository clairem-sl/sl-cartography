# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import pickle
import re
import time
from datetime import datetime
from itertools import chain
from multiprocessing import Event
from pathlib import Path
from typing import Final, Protocol, cast

from PIL import Image

from cartographer_v4.grid import ExclusionMethod, GridMaker
from sl_maptools import AreaBounds, AreaDescriptor, CoordType, RegionsDBRecord3
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader, Settable, SLMapToolsConfig, handle_sigint
from sl_maptools.validator import get_bonnie_coords, inventorize_maps_latest

Config: SLMapToolsConfig = ConfigReader("config.toml")
AbortRequested: Settable = Event()


class CartographerOptions(Protocol):
    """
    Options unique for this module
    """
    no_grid: bool
    continents: list[str]
    areas: list[AreaBounds]
    mapdir: Path
    outdir: Path
    regionsdb: Path
    overwrite: bool
    exclusion_method: ExclusionMethod
    no_bonnie: bool


class Options(CartographerOptions, Protocol):
    """
    Options combined from this module and common ones
    """
    pass


class AreaParser(argparse.Action):
    """
    Parses area notation
    """

    RE_AREA: Final[re.Pattern] = re.compile(r"(?P<x1>\d+)[,:-](?P<y1>\d+)[,:-](?P<x2>\d+)[,:-](?P<y2>\d+)")

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ANN001, ARG002
        """
        Perform parsing of area notation

        :param parser: ArgumentParser object
        :param namespace: ArgumentParser's parse-result namespace
        :param values: An iterable containing values to parse
        :param option_string: Options
        """
        re_area = self.RE_AREA
        rslt = []
        for value in values:
            try:
                m = re_area.match(value)
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
    """
    Get options from CLI
    """
    parser = argparse.ArgumentParser("cartographer_v4")

    parser.add_argument("--no-grid", action="store_true", help="Skip creation of grid overlay")

    parser.add_argument(
        "--continents",
        type=str,
        nargs="+",
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
        "--regionsdb",
        type=Path,
        default=Path(Config.names.dir) / Config.names.db,
        help="RegionsDB for validation. If not specified, use names.db in config.toml",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="If specified, overwrite existing hi-res map file.",
    )
    parser.add_argument(
        "--exclusion-method",
        metavar="METHOD",
        type=ExclusionMethod.__members__.get,
        choices=ExclusionMethod.__members__.values(),
        default="HIDE",
        help="One of " + ", ".join(ExclusionMethod.__members__.keys())
    )
    parser.add_argument(
        "--no-bonnie",
        action="store_true",
        default=False,
        help="If specified, do not perform validation against BonnieBots database"
    )

    _opts = parser.parse_args()
    if _opts.outdir is None:
        _opts.outdir = _opts.mapdir
    return cast(Options, _opts)


def make_map(
    targ: Path,
    area: AreaDescriptor,
    map_tiles: dict[CoordType, Path],
    exclusion_method: ExclusionMethod,
) -> None:
    """
    Actually create the map file
    """
    print(f"{area.bounding_box}", end="", flush=True)
    csize_x = (area.x_eastmost - area.x_westmost + 1) * 256
    csize_y = (area.y_northmost - area.y_southmost + 1) * 256
    canvas = Image.new("RGBA", (csize_x, csize_y))

    if exclusion_method is ExclusionMethod.HIDE:
        xy_iterator = area.xy_iterator
    else:
        xy_iterator = area.bounding_box.xy_iterator
    c = 0
    for x, y in xy_iterator():
        # print(coord)
        if (x, y) not in map_tiles:
            continue
        c += 1
        if (c % 10) == 0:
            print(".", end="", flush=True)
        canv_x = (x - area.x_westmost) * 256
        canv_y = (area.y_northmost - y) * 256
        with Image.open(map_tiles[x, y]) as img:
            img.load()
            if exclusion_method is ExclusionMethod.TRANSP and (x, y) not in area:
                img.putalpha(63)
            canvas.paste(img, (canv_x, canv_y))

    # print(targ)
    canvas.save(targ)


def main(opts: Options) -> None:  # noqa: D103
    start = time.monotonic()

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    wanted_areas: list[tuple[str, AreaDescriptor]] = []
    if not opts.areas:
        if not opts.continents:
            wanted_areas.extend(
                (name, area_desc) for name, area_desc in KNOWN_AREAS.items() if area_desc.automatic
            )
        else:
            for aa in chain(map(lambda s: s.split(","), opts.continents)):
                for a in aa:
                    wanted_areas.extend((a, KNOWN_AREAS[a]))
    else:
        for a in opts.areas:
            aname = f"{a.x_westmost}-{a.y_southmost}-{a.x_eastmost}-{a.y_northmost}-{ts}"
            wanted_areas.append((aname, AreaDescriptor(includes=a)))
        if opts.continents:
            for aa in chain(map(lambda s: s.split(","), opts.continents)):
                for a in aa:
                    wanted_areas.extend((a, KNOWN_AREAS[a]))

    with opts.regionsdb.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)  # noqa: S301
    validation_set: set[CoordType] = {
        k for k, v in regsdb.items() if v["current_name"]
    }

    if not opts.no_bonnie:
        bonnie_coords = get_bonnie_coords(None, True)
        validation_set.intersection_update(bonnie_coords)

    map_tiles = inventorize_maps_latest(opts.mapdir)
    for k in [co for co in map_tiles if co not in validation_set]:
        del map_tiles[k]

    print("\nMaking maps:")
    new_count = 0
    with handle_sigint(AbortRequested):
        if not opts.no_grid:
            grid_maker = GridMaker(regions_db=regsdb, validation_set=validation_set)
        for area_name, area_desc in wanted_areas:
            targdir = opts.outdir / area_name
            targdir.mkdir(parents=True, exist_ok=True)
            print(f"{area_name}: ", end="", flush=True)
            targ = targdir / (area_name + ".png")
            if not opts.overwrite and targ.exists():
                print("Already exists", end="")
            else:
                print("🌐", end="", flush=True)
                make_map(targ, area_desc, map_tiles, opts.exclusion_method)
                new_count += 1
            print(f"\n  => {targ}", flush=True)
            if not opts.no_grid:
                grid_maker.make_grid(targ, overwrite=opts.overwrite, exclusion_method=opts.exclusion_method)
                print()
            if AbortRequested.is_set():
                break

    finish = time.monotonic()
    print("=" * 40)
    print(f"{len(wanted_areas)} areas processed, {new_count} new")
    print(f"Finished in {finish - start:_.2f} seconds.")


if __name__ == "__main__":
    options = get_options()
    main(options)
