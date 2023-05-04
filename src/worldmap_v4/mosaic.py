import argparse
import pickle
import re

from pathlib import Path
from typing import Any

from PIL import Image

from sl_maptools.image_processing import FASCIA_COORDS, RGBTuple, calculate_dominant_colors
from worldmap_v4 import get_bonnie_coords


RE_REGMAP_FN: re.Pattern = re.compile(r"^(\d+)-(\d+)_\d+-\d+.jpg$")

def get_opts():
    parser = argparse.ArgumentParser("worldmap_v4.mosaic")

    parser.add_argument("--domcdb", type=Path)
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
MapFiles: dict[Coord, list[Path]] = {}

def make_mosaic(coordinates: set[Coord], canvas_size: Coord, fascia_per_side: int, tilesize: int):
    fascia_size = round(tilesize / fascia_per_side)
    fasc_box = (fascia_size, fascia_size)
    slab_size = fascia_size * fascia_per_side

    canvas = Image.new("RGBA", canvas_size)

    for coord in coordinates:

        if (domc_by_size := DominantColorsDB.get(coord)) is None:
            if (fp := MapFiles.get(coord)) is None:
                continue
            with fp[-1].open("rb") as fin:
                img = Image.open(fin)
                img.load()
            domcs = calculate_dominant_colors(img, fascia_per_side)
            DominantColorsDB[coord] = {fascia_per_side: domcs}
        elif (domcs := domc_by_size.get(fascia_per_side)) is None:
            if (fp := MapFiles.get(coord)) is None:
                continue
            with fp[-1].open("rb") as fin:
                img = Image.open(fin)
                img.load()
            domcs = calculate_dominant_colors(img, fascia_per_side)
            DominantColorsDB[coord].update({fascia_per_side: domc})

        if len(domcs) != (fascia_per_side * fascia_per_side):
            raise ValueError()

        canv_x = coord[0] * slab_size
        canv_y = (2100 - coord[1]) * slab_size

        sx = sy = 0
        for clr in domcs:
            fasc_img = Image.new("RGB", fasc_box, color=clr)
            canvas.paste(fasc_img, (canv_x + sx, canv_y + sy))
            sy += fascia_size
            if sy >= slab_size:
                sy = 0
                sx += fascia_size

    canvas.save(f"worldmap_v4_mosaic_{fascia_per_side}x{fascia_per_side}.png")


def main(domcdb: Path, regionsdb: Path, mapdir: Path, bonniedb: Path, fetchbonnie: bool, tilesize: int):
    global DominantColorsDB, RegionsDB

    if not regionsdb.exists():
        raise FileNotFoundError(f"Can't find RegionsDB {regionsdb}")
    if not mapdir.exists() or not mapdir.is_dir():
        raise NotADirectoryError(f"Can't find MapsDir {mapdir}")

    for fp in sorted(mapdir.glob("*.jpg")):
        if (m := RE_REGMAP_FN.match(fp.name)) is None:
            continue
        co = (int(m.group(1)), int(m.group(2)))
        MapFiles.setdefault(co, []).append(fp)

    if domcdb.exists():
        with domcdb.open("rb") as fin:
            DominantColorsDB = pickle.load(fin)

    with regionsdb.open("rb") as fin:
        RegionsDB.update(pickle.load(fin))
    coords_to_process = set(RegionsDB.keys())

    bonnie_coords = get_bonnie_coords(bonniedb, fetchbonnie)
    coords_to_process.intersection_update(bonnie_coords)

    for fsc in FASCIA_COORDS:
        make_mosaic(coords_to_process, (2100, 2100), fsc, tilesize)


if __name__ == '__main__':
    opts = get_opts()
    main(**vars(opts))
