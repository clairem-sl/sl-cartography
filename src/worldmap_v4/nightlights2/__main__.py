# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import importlib
import pickle
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast

from PIL import Image, ImageDraw

from sl_maptools import COORD_RANGE, MapCoord, RegionsDBRecord
from sl_maptools.utils import ConfigReader, make_backup
from sl_maptools.validator import get_bonnie_coords, inventorize_maps_all
from worldmap_v4.nightlights2 import TilerBase


TilerClass: type|None = None

Config = ConfigReader("config.toml")

DEFA_DB_PATH: Final[Path] = Path(Config.names.dir) / Config.names.db
DEFA_MAPDIR: Final[Path] = Path(Config.maps.dir)
DEFA_OUTDIR: Final[Path] = Path(Config.nightlights.dir)

MIN_X: Final[int] = COORD_RANGE.min_
MAX_X: Final[int] = COORD_RANGE.max_

MIN_Y: Final[int] = COORD_RANGE.min_
MAX_Y: Final[int] = COORD_RANGE.max_

DEFA_REGION_SZ: Final[int] = 9
"""Size of each region in the Nightlights map, in units of pixels"""
BLACK: Final = 0
"""Definition of 'black' color. You will need to ensure the data format is suitable for the image type."""
WHITE: Final = 255
"""Definition of 'white' color. You will need to ensure the data format is suitable for the image type."""


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
    parser.add_argument("--no-maptiles", action="store_true", default=False, help="Don't validate against MapTiles collection")

    parser.add_argument("--tiler", default="7x7")

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


def make_nightlights(regions: set[MapCoord], *, region_size: int = DEFA_REGION_SZ) -> Image.Image:
    slab_sz, _rem = divmod(region_size, 3)
    if _rem:
        raise ValueError("region_size must be an integer multiple of 3!")

    width = MAX_X - MIN_X + 1
    height = MAX_Y - MIN_Y + 1

    def box(value: int) -> tuple[int, int]:
        return value, value

    canvas_box = MapCoord(width, height) * region_size
    canvas = Image.new("L", canvas_box, color=BLACK)
    slab_w = Image.new("L", box(slab_sz), color=WHITE)

    def world_has_all_of(*coords: MapCoord) -> bool:
        return not any(co not in regions for co in coords)

    def world_has_none_of(*coords: MapCoord) -> bool:
        return not any(co in regions for co in coords)


    for coord in regions:
        # region Compass points coordinates
        c_n = coord + (0, 1)
        c_e = coord + (1, 0)
        c_w = coord - (1, 0)
        c_s = coord - (0, 1)
        c_ne = coord + (1, 1)
        c_nw = coord + (-1, 1)
        c_se = coord + (1, -1)
        c_sw = coord + (-1, -1)
        # endregion

        region_img = Image.new("L", box(region_size), color=BLACK)
        region_img.paste(slab_w, box(slab_sz))
        draw = ImageDraw.Draw(region_img)

        # region Vertical & Horizontal connections
        if world_has_all_of(c_n):
            region_img.paste(slab_w, (slab_sz, 0))
        if world_has_all_of(c_e):
            region_img.paste(slab_w, (slab_sz * 2, slab_sz))
        if world_has_all_of(c_w):
            region_img.paste(slab_w, (0, slab_sz))
        if world_has_all_of(c_s):
            region_img.paste(slab_w, (slab_sz, slab_sz * 2))
        # endregion

        # region Diagonals

        # Far all these:
        # if has_vert_neighbor and has_horiz_neighbor:
        #   if also has_diag_neighbor_between_vert_and_horiz:
        #     plop a slab
        #   else:
        #     chamfer_inner_corner
        #   -plus-
        #   if no_neighbor_on_other_sides:
        #     chamfer_outer_corner

        if world_has_all_of(c_n, c_e):
            if world_has_all_of(c_ne):
                region_img.paste(slab_w, (slab_sz * 2, 0))
            else:
                draw.point((slab_sz * 2, slab_sz - 1), fill=WHITE)
            if world_has_none_of(c_s, c_sw, c_w):
                draw.point((slab_sz, slab_sz * 2 - 1), fill=BLACK)

        if world_has_all_of(c_n, c_w):
            if world_has_all_of(c_nw):
                region_img.paste(slab_w, (0, 0))
            else:
                draw.point(box(slab_sz - 1), fill=WHITE)
            if world_has_none_of(c_s, c_se, c_e):
                draw.point(box(slab_sz * 2 - 1), fill=BLACK)

        if world_has_all_of(c_s, c_e):
            if world_has_all_of(c_se):
                region_img.paste(slab_w, box(slab_sz * 2))
            else:
                draw.point(box(slab_sz * 2), fill=WHITE)
            if world_has_none_of(c_n, c_nw, c_w):
                draw.point((slab_sz, slab_sz), fill=BLACK)

        if world_has_all_of(c_s, c_w):
            if world_has_all_of(c_sw):
                region_img.paste(slab_w, (0, slab_sz * 2))
            else:
                draw.point((slab_sz - 1, slab_sz * 2), fill=WHITE)
            if world_has_none_of(c_n, c_ne, c_e):
                draw.point((slab_sz * 2 - 1, slab_sz), fill=BLACK)

        # endregion

        canvas.paste(region_img, canvas_coord(*coord, region_size))

    return canvas


def make_nightlights2(regions: set[MapCoord], *, tiler_class: type[TilerBase]) -> Image.Image:
    width = MAX_X - MIN_X + 1
    height = MAX_Y - MIN_Y + 1

    def box(value: int) -> tuple[int, int]:
        return value, value

    region_size = tiler_class.Size
    canvas_box = cast(tuple[int, int], MapCoord(width, height) * region_size)
    canvas = Image.new("L", canvas_box, color=BLACK)

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
        bonnie_coords.clear()
        del bonnie_coords

    # Filter with Maptiles if not prevented
    if not opts.no_maptiles:
        # Get Maptiles data
        mapfiles = inventorize_maps_all(opts.mapdir)
        regions.intersection_update(mapfiles.keys())
        mapfiles.clear()
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
