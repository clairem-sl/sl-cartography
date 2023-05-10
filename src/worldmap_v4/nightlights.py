# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle

import httpx
import ruamel.yaml as ryaml

from pathlib import Path
from typing import Any, Final, Protocol, TypedDict, cast

from PIL import Image, ImageDraw

from sl_maptools import MapCoord, inventorize_maps_all, RegionsDBRecord
from worldmap_v4 import BONNIE_REGDB_URL, get_bonnie_coords

DEFA_DB_PATH: Final[Path] = Path(r"C:\Cache\SL-Carto\RegionsDB2.pkl")
DEFA_MAPDIR: Final[Path] = Path(r"C:\Cache\SL-Carto\Maps2")

MIN_X: Final[int] = 0
MAX_X: Final[int] = 2100

MIN_Y: Final[int] = 0
MAX_Y: Final[int] = 2100

DEFA_REGION_SZ: Final[int] = 9
"""Size of each region in the Nightlights map, in units of pixels"""
BLACK: Final = 0
"""Definition of 'black' color. You will need to ensure the data format is suitable for the image type."""
WHITE: Final = 255
"""Definition of 'white' color. You will need to ensure the data format is suitable for the image type."""


class Options(Protocol):
    dbpath: Path
    mapdir: Path
    no_validate: bool
    bonniedb: Path
    fetchbonnie: bool
    force: bool
    mosaicfile: Path


class BonnieRegionData(TypedDict):
    region_name: str
    region_x: int
    region_y: int


def get_opts():
    parser = argparse.ArgumentParser("worldmap_v4.nightlights")

    parser.add_argument("--dbpath", type=Path, default=DEFA_DB_PATH)
    parser.add_argument("--mapdir", type=Path, default=DEFA_MAPDIR)
    parser.add_argument("--no-validate", action="store_true")

    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--bonniedb", type=Path, default=None)
    grp.add_argument("--fetchbonnie", action="store_true")

    parser.add_argument("mosaicfile", type=Path)

    parser.add_argument("--force", action="store_true")

    _opts = parser.parse_args()

    return _opts


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


def make_map(opts: Options):
    dbpath = opts.dbpath
    bonniedb = opts.bonniedb

    if not opts.force and opts.mosaicfile.exists():
        raise FileExistsError(f"{opts.mosaicfile} already exists but --force not specified!")

    print(f"Reading Auditor's DB from {dbpath} ... ", end="", flush=True)
    with dbpath.open("rb") as fin:
        data_raw: dict[tuple[int, int], RegionsDBRecord] = pickle.load(fin)
    print(flush=True)

    regions: set[tuple[int, int]] = set(k for k, v in data_raw.items() if v["current_name"])
    if not opts.no_validate:
        bonnie_coords = get_bonnie_coords(bonniedb, opts.fetchbonnie)
        if bonnie_coords:
            regions.intersection_update(bonnie_coords)
            print(flush=True)
        mapfiles = inventorize_maps_all(opts.mapdir)
        regions.intersection_update(mapfiles.keys())

    print("Creating Nightlights Map ... ", end="", flush=True)
    canvas = make_nightlights({MapCoord(x, y) for x, y in regions})
    print("\nSaving nightlights mosaic ... ", end="", flush=True)
    if opts.mosaicfile.parent.name:
        targ = opts.mosaicfile.with_suffix(".png")
    else:
        targ = (opts.mapdir / opts.mosaicfile).with_suffix(".png")
    targ.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(targ, optimize=True)
    print(f"\nNightlights mosaic saved to {opts.mosaicfile}")


if __name__ == '__main__':
    make_map(cast(Options, get_opts()))
