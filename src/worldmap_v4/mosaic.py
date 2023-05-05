import argparse
import pickle
import re

import multiprocessing as MP
import multiprocessing.pool as MPPool

from pathlib import Path
from typing import Any, TypedDict

from PIL import Image

from sl_maptools.image_processing import RGBTuple, calculate_dominant_colors, FASCIA_SIZES
from worldmap_v4 import get_bonnie_coords


RE_REGMAP_FN: re.Pattern = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_\d+-\d+.jpg$")


def get_opts():
    parser = argparse.ArgumentParser("worldmap_v4.mosaic")

    parser.add_argument("--regionsdb", type=Path)
    parser.add_argument("--mapdir", type=Path)
    parser.add_argument("--tilesize", type=int, default=9)

    grp_bonnie = parser.add_mutually_exclusive_group()
    grp_bonnie.add_argument("--bonniedb", type=Path)
    grp_bonnie.add_argument("--fetchbonnie", action="store_true")

    _opts = parser.parse_args()

    return _opts


Coord = tuple[int, int]
DominantColorsDB: dict[Coord, dict[int, list[RGBTuple]]] = {}
RegionsDB: dict[Coord, Any] = {}
MapFiles: dict[Coord, Path] = {}


class JobDict(TypedDict):
    coord: Coord
    mapfile: Path


def calc_domc(job: tuple[Coord, Path]):
    coord, mapfile = job
    with mapfile.open("rb") as fin:
        img = Image.open(fin)
        img.load()
    domc: dict[int, list[RGBTuple]] = {
        fsz: calculate_dominant_colors(img, fsz) for fsz in FASCIA_SIZES
    }
    return coord, domc


def make_mosaic(data: dict[Coord, list[RGBTuple]], tilesize: int, max_coords: Coord):
    """
    :param data: world data to mosaicize
    :param tilesize: size of 'tile' (representation of a region in mosaic map)
    :param max_coords: highest coordinates on both x- and y-axis
    """
    fascias_per_tile = next(iter(data.values()))
    fascia_per_side = int(len(fascias_per_tile) ** 0.5)
    fascia_size = round(tilesize / fascia_per_side)
    fasc_box = (fascia_size, fascia_size)
    tilesize = fascia_per_side * fascia_size

    xmax, ymax = max_coords
    canvas_box = (xmax + 1) * tilesize, (ymax + 1) * tilesize
    canvas = Image.new("RGBA", canvas_box)

    for coord, domc in data.items():
        x, y = coord
        canv_x = x * tilesize
        canv_y = (ymax - y) * tilesize

        sx = sy = 0
        for clr in domc:
            fasc_img = Image.new("RGB", fasc_box, color=clr)
            canvas.paste(fasc_img, (canv_x + sx, canv_y + sy))
            sy += fascia_size
            if sy >= tilesize:
                sy = 0
                sx += fascia_size

    targ = f"worldmap_v4_mosaic_{fascia_per_side}x{fascia_per_side}.png"
    canvas.save(targ)
    print(targ)


def main(regionsdb: Path, mapdir: Path, bonniedb: Path, fetchbonnie: bool, tilesize: int):
    global DominantColorsDB, RegionsDB, MapFiles

    if not regionsdb.exists():
        raise FileNotFoundError(f"Can't find RegionsDB {regionsdb}")
    if not mapdir.exists() or not mapdir.is_dir():
        raise NotADirectoryError(f"Can't find MapsDir {mapdir}")

    with regionsdb.open("rb") as fin:
        RegionsDB.update(pickle.load(fin))
    coords_to_process = set(RegionsDB.keys())

    bonnie_coords = get_bonnie_coords(bonniedb, fetchbonnie)
    coords_to_process.intersection_update(bonnie_coords)

    _mapfiles = {}
    for fp in sorted(mapdir.glob("*.jpg"), reverse=True):
        if (m := RE_REGMAP_FN.match(fp.name)) is None:
            continue
        co = (int(m.group("x")), int(m.group("y")))
        if co in coords_to_process and co not in _mapfiles:
            _mapfiles[co] = fp
    MapFiles = {
        co: mf for co, mf in sorted(_mapfiles.items(), key=lambda v: (v[0][1], v[0][0]))
    }
    print(f"{len(MapFiles)} regions to mosaicize.")

    print(f"Calculating dominant colors ", end="", flush=True)
    world_domc: dict[int, dict[Coord, list[RGBTuple]]] = {n: {} for n in FASCIA_SIZES}
    pool: MPPool.Pool
    with MP.Pool() as pool:
        for i, result in enumerate(pool.imap_unordered(calc_domc, MapFiles.items()), start=1):
            coord, domc = result
            for fsz, cols in domc.items():
                world_domc[fsz][coord] = cols
            if (i % 100) == 0:
                print(".", end="", flush=True)
    print("✅")

    for fsz in FASCIA_SIZES:
        print(f"Making {fsz}x{fsz} mosaic ... ", end="", flush=True)
        make_mosaic(world_domc[fsz], tilesize, (2100, 2100))


if __name__ == '__main__':
    opts = get_opts()
    main(**vars(opts))
