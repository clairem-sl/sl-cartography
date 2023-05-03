# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
import re
from itertools import product

import httpx
import ruamel.yaml as ryaml

from pathlib import Path
from typing import Any, Final, Protocol, TypedDict, cast

from PIL import Image

from sl_maptools import MapCoord


RE_MAPFILE = re.compile(r"^(\d+)-(\d+)_\d")


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


FASCIA_COORDS: dict[int, list[tuple[int, int, int, int]]] = {
    1: [(0, 0, 256, 256)],
    2: [getbox(2, 1, x, y) for x, y in tuptup(0, 1)],
    3: [getbox(16, 6, x, y) for x, y in tuptup(0, 5, 10)],
    4: [getbox(4, 1, x, y) for x, y in tuptup(0, 1, 2, 3)],
    5: [getbox(128, 28, x, y) for x, y in tuptup(0, 25, 50, 75, 100)],
}
FASCIA_SIZES: dict[int, int] = {
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


class BonnieRegionData(TypedDict):
    region_name: str
    region_x: int
    region_y: int


def get_opts():
    parser = argparse.ArgumentParser("worldmap_v4.mosaic")

    parser.add_argument("--dbpath", type=Path, default=DEFA_DB_PATH)
    parser.add_argument("--mapdir", type=Path, default=DEFA_MAPS_DIR)

    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--bonniedb", type=Path, default=None)
    grp.add_argument("--fetchbonnie", action="store_true")

    parser.add_argument("--force", action="store_true")

    _opts = parser.parse_args()

    return _opts


MapFiles: dict[tuple[int, int], Path] = {}

def make_one_mosaic(mo_pattern: int, regions: set[MapCoord], mapdir: Path):
    fascia_size = FASCIA_SIZES[mo_pattern]
    slab_size = fascia_size * mo_pattern
    width = MAX_X - MIN_X + 1
    height = MAX_Y - MIN_Y + 1
    canvas_size = MapCoord(width, height) * slab_size
    canvas = Image.new("RGBA", canvas_size)
    fascia_box = MapCoord(fascia_size, fascia_size)
    # slab_box = MapCoord(slab_size, slab_size)

    targ = mapdir / f"worldmap_mosaic_v4_{mo_pattern}x{mo_pattern}.png"
    print(f"\nSaving as {targ}")
    print(f"Creating {mo_pattern}x{mo_pattern} ", end="", flush=True)
    for i, coord in enumerate(regions, start=1):
        if i % 100 == 0:
            canvas.save(targ)
            print(".", end="", flush=True)
        if coord not in MapFiles:
            continue
        mapfile = MapFiles[coord]
        # print(mapfile, end=" ")
        with mapfile.open("rb") as fin:
            regimg = Image.open(fin)
            regimg.load()
        fx = (coord.x - MIN_X) * fascia_size
        fy = (MAX_Y - coord.y) * fascia_size
        sx = sy = 0
        for fascia in FASCIA_COORDS[mo_pattern]:
            # print(fascia, end=" ")
            fascia_img = regimg.crop(fascia)
            quant = fascia_img.quantize(colors=16, kmeans=3)
            rgb = quant.convert("RGB")
            colors = cast(list[tuple[int, tuple[int, int, int]]], rgb.getcolors())
            freq, dom = max(colors, key=lambda x: x[0])
            # print(dom)
            loc = fx + sx, fy + sy
            canvas.paste(Image.new("RGB", fascia_box, color=dom), loc)
            sy += fascia_size
            if sy >= slab_size:
                sy = 0
                sx += fascia_size

    canvas.save(targ)
    print(f"Saved to {targ}")


def make_mosaic(mapdir: Path, regions: set[MapCoord]):
    for mo in FASCIA_COORDS:
        make_one_mosaic(mo, regions, mapdir)


def make_map(opts: Options):
    dbpath = opts.dbpath
    bonniedb = opts.bonniedb

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

    print("Inventorizing region maps ... ", end="", flush=True)
    all_maps = sorted(opts.mapdir.glob("*.jpg"))
    for mapfile in all_maps:
        m = RE_MAPFILE.match(mapfile.name)
        x = int(m.group(1))
        y = int(m.group(2))
        MapFiles[x, y] = mapfile

    print("\nCreating Mosaic Maps ... ", end="", flush=True)
    make_mosaic(opts.mapdir, {MapCoord(x, y) for x, y in regions})
    # print("\nSaving nightlights mosaic ... ", end="", flush=True)
    # opts.mosaicfile.parent.mkdir(parents=True, exist_ok=True)
    # canvas.save(opts.mosaicfile, optimize=True)
    # print(f"\nNightlights mosaic saved to {opts.mosaicfile}")


if __name__ == '__main__':
    make_map(cast(Options, get_opts()))
