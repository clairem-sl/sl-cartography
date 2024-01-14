# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import importlib
import pickle
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast

from PIL import Image

from sl_maptools import COORD_RANGE, MapCoord, RegionsDBRecord
from sl_maptools.utils import ConfigReader, make_backup
from sl_maptools.validator import get_bonnie_coords, inventorize_maps_all
from worldmap_v4.nightlights2 import TilerBase


TilerClass: type | None = None

Config = ConfigReader("config.toml")

DEFA_DB_PATH: Final[Path] = Path(Config.names.dir) / Config.names.db
DEFA_MAPDIR: Final[Path] = Path(Config.maps.dir)
DEFA_OUTDIR: Final[Path] = Path(Config.nightlights.dir)

MIN_X: Final[int] = COORD_RANGE.min_
MAX_X: Final[int] = COORD_RANGE.max_

MIN_Y: Final[int] = COORD_RANGE.min_
MAX_Y: Final[int] = COORD_RANGE.max_


class Options(Protocol):
    """Options returned from command line"""

    dbpath: Path
    mapdir: Path
    outdir: Path
    no_bonnie: bool
    no_maptiles: bool
    tiler: str


class BonnieRegionData(TypedDict):
    """Relevant data extracted from BonnieBots DB"""

    region_name: str
    region_x: int
    region_y: int


def get_options() -> Options:
    """Get options from command line"""
    parser = argparse.ArgumentParser("worldmap_v4.nightlights")

    parser.add_argument("--dbpath", type=Path, default=DEFA_DB_PATH)
    parser.add_argument("--mapdir", type=Path, default=DEFA_MAPDIR)
    parser.add_argument("--outdir", type=Path, default=DEFA_OUTDIR)

    parser.add_argument("--no-bonnie", action="store_true", default=False, help="Don't validate against BonnieBots DB")
    parser.add_argument(
        "--no-maptiles", action="store_true", default=False, help="Don't validate against MapTiles collection"
    )

    parser.add_argument("--tiler", default="8x8")

    _opts = parser.parse_args()

    return cast(Options, _opts)


def canvas_coord(region_x: int, region_y: int, multiplier: int = 1) -> tuple[int, int]:
    """
    Converts geo-coords (in units of Regions) to canvas coords (in units of pixels)

    This is not a simple multiplied-items tuple like what's implemented by MapCoord.__mul__

    This method implements the shift, reflect, and multiplication necessary to do the conversion.

    :param region_x: X geo-coordinate of the Region
    :param region_y: Y geo-coordinate of the Region
    :param multiplier: Optional multiplier
    :return: The canvas coordinate for the Region
    """
    return (region_x - MIN_X) * multiplier, (MAX_Y - region_y) * multiplier


def make_nightlights2(regions: set[MapCoord], *, tiler_class: type[TilerBase]) -> Image.Image:
    """
    Actually create the Nightlights map, given a set of coordinates and a tiler class

    :param regions: Set of regions which we will map
    :param tiler_class: The class to be used to create the actual map
    :return: A completed map
    """
    width = MAX_X - MIN_X + 1
    height = MAX_Y - MIN_Y + 1

    region_size = tiler_class.Size
    canvas_box = cast(tuple[int, int], MapCoord(width, height) * region_size)
    canvas = Image.new("L", canvas_box, color=0)

    tiler = tiler_class(regions)
    for coord in regions:
        region_img = tiler.maketile(coord)
        canvas.paste(region_img, canvas_coord(*coord, region_size))

    return canvas


def main(opts: Options):
    tiler_module = importlib.import_module(f"worldmap_v4.nightlights2.tiler_{opts.tiler}")

    # Read Regions from DB
    with opts.dbpath.open("rb") as fin:
        data_raw: dict[tuple[int, int], RegionsDBRecord] = pickle.load(fin)  # noqa: S301
    regions: set[tuple[int, int]] = set(k for k, v in data_raw.items() if v["current_name"])

    # Filter with Bonnie if not prevented
    if not opts.no_bonnie:
        # Get Bonnie data
        bonnie_coords = get_bonnie_coords(None, True)
        if bonnie_coords:
            regions.intersection_update(bonnie_coords)
            print(flush=True)
        del bonnie_coords

    # Filter with Maptiles if not prevented
    if not opts.no_maptiles:
        # Get Maptiles data
        mapfiles = inventorize_maps_all(opts.mapdir)
        regions.intersection_update(mapfiles.keys())
        del mapfiles

    _ts = datetime.now().strftime("%y%m%d-%H%M")
    targ = opts.outdir / f"worldmap4_nightlights_{_ts}.png"
    if targ.exists():
        make_backup(targ)
        targ.unlink()

    print("Creating Nightlights Map ... ", end="", flush=True)
    canvas = make_nightlights2({MapCoord(x, y) for x, y in regions}, tiler_class=tiler_module.Tiler)

    print("\nSaving nightlights mosaic ... ", end="", flush=True)
    targ.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(targ, optimize=True)

    print(f"\nNightlights mosaic saved to {targ}")


if __name__ == "__main__":
    main(get_options())
