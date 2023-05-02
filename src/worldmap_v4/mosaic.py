# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
from itertools import product
from math import isqrt

import httpx
import ruamel.yaml as ryaml

from pathlib import Path
from typing import Any, Final, Iterable, Protocol, TypedDict, cast, Sized, Sequence

from PIL import Image, ImageDraw

from sl_maptools import MapCoord, MapRegion
from worldmap_v4.color_processing import DominantColors


BONNIE_REGDB_URL = "https://www.bonniebots.com/static-api/regions/index.json"
DEFA_DB_PATH: Final[Path] = Path(r"C:\Cache\SL-Carto\RegionsDB.pkl")
DEFA_MAPS_DIR: Final[Path] = Path("C:\\Cache\\SL-Carto\\Maps\\")

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

DEFA_MOSAIC_SLAB_SZ: Final[int] = 2


def getbox(fascias_per_side: int, subreg_sz: int, x_offset: int, y_offset: int) -> tuple[int, int, int, int]:
    """
    Returns proper box tuple for image cropping

    :param fascias_per_side: Split region to how many fascias per dimension (we'll get splits x splits number of fascias)
    :param subreg_sz: How many fascias per slab (subreg_sz x subreg_sz fascias per slab)
    :param x_offset: Slab offset from left
    :param y_offset: Slab offset from top
    :return: Box tuple suitable for pillow's Image.crop()
    """
    fascia_size = 256 // fascias_per_side
    return (
        x_offset * fascia_size,
        y_offset * fascia_size,
        (x_offset + subreg_sz) * fascia_size,
        (y_offset + subreg_sz) * fascia_size,
    )


def tuptup(*items):
    yield from product(items, items)


SLABS: dict[int, list[tuple[int, int, int, int]]] = {
    1: [(0, 0, 256, 256)],
    2: [getbox(2, 1, x, y) for x, y in tuptup(0, 1)],
    3: [getbox(16, 6, x, y) for x, y in tuptup(0, 5, 10)],
    4: [getbox(4, 1, x, y) for x, y in tuptup(0, 1, 2, 3)],
    5: [getbox(128, 28, x, y) for x, y in tuptup(0, 25, 50, 75, 100)],
}
SLAB_SIZES: dict[int, int] = {
    1: 3,
    2: 3,
    3: 3,
    4: 2,
    5: 2,
}


class Options(Protocol):
    dbpath: Path
    bonniedb: Path
    fetchbonnie: bool
    force: bool
    mosaicfile: Path
    mapdir: Path
    slabsize: int


class BonnieRegionData(TypedDict):
    region_name: str
    region_x: int
    region_y: int


def get_opts():
    parser = argparse.ArgumentParser("worldmap_v4.nightlights")

    parser.add_argument("--dbpath", type=Path, default=DEFA_DB_PATH)
    parser.add_argument("--mapdir", type=Path, default=DEFA_MAPS_DIR)
    parser.add_argument("--slabsize", type=int, default=DEFA_MOSAIC_SLAB_SZ)

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


def make_mosaic_one(domc_all: dict[MapCoord, DominantColors], mosaic_keys: Sequence[str], *, slab_size: int = 2):
    _dim = 1 + isqrt(len(mosaic_keys) - 1)
    width = MAX_X - MIN_X + 1
    height = MAX_Y - MIN_Y + 1
    canvas_size = MapCoord(width, height) * slab_size * _dim
    canvas = Image.new("RGBA", canvas_size)
    slab_box = MapCoord(slab_size, slab_size)
    mosaic_box = slab_box * _dim
    smax = _dim * slab_size

    for coord, domc in domc_all.items():
        mosaic_tile = Image.new("RGBA", mosaic_box)
        sx = sy = 0
        for colr in domc.to_list(*mosaic_keys):
            slab = Image.new("RGB", slab_box, color=colr)
            mosaic_tile.paste(slab, (sx, sy))
            sx += slab_size
            if sx >= smax:
                sx = 0
                sy += slab_size
        canvas.paste(mosaic_tile, canvas_coord(*coord, mosaic_box.x))


def make_mosaic(mapdir: Path, regions: set[MapCoord], *, slab_size: int) -> Image.Image:
    width = MAX_X - MIN_X + 1
    height = MAX_Y - MIN_Y + 1

    for mo in range(1, 6):


    canvas_size = MapCoord(width, height) * slab_size

    def box(value: int) -> tuple[int, int]:
        return value, value

    canvas_box = MapCoord(width, height) * region_size
    canvas = Image.new("L", canvas_box, color=BLACK)
    slab_w = Image.new("L", box(slab_sz), color=WHITE)

    def world_has_all_of(*coords: MapCoord) -> bool:
        return all(map(regions.__contains__, coords))

    def world_has_none_of(*coords: MapCoord) -> bool:
        return not any(map(regions.__contains__, coords))

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
        data_raw: dict[tuple[int, int], Any] = pickle.load(fin)
    print(flush=True)

    regions: set[tuple[int, int]] = set(data_raw)
    bdb_data_raw = {}
    if bonniedb:
        print(f"Reading BonnieBots Regions DB from {bonniedb} ... ", end="", flush=True)
        with bonniedb.open("rb") as fin:
            bdb_data_raw = ryaml.safe_load(fin)
    elif opts.fetchbonnie:
        print(f"Fetching BonnieBots Regions DB ... ", end="", flush=True)
        with httpx.Client(timeout=10) as client:
            resp = client.get(BONNIE_REGDB_URL)
            bdb_data_raw = resp.json()
    bonnie_coords = {(record["region_x"], record["region_y"]) for record in bdb_data_raw["regions"]}
    if bonnie_coords:
        regions = regions.intersection(bonnie_coords)
        print(flush=True)

    print("Creating Nightlights Map ... ", end="", flush=True)
    canvas = make_mosaic(opts.mapdir, {MapCoord(x, y) for x, y in regions}, slab_size=opts.slabsize)
    print("\nSaving nightlights mosaic ... ", end="", flush=True)
    opts.mosaicfile.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(opts.mosaicfile, optimize=True)
    print(f"\nNightlights mosaic saved to {opts.mosaicfile}")


if __name__ == '__main__':
    make_map(cast(Options, get_opts()))
