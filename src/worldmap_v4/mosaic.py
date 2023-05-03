import argparse
import pickle

from pathlib import Path
from typing import Any

from sl_maptools.image_processing import RGBTuple
from worldmap_v4 import get_bonnie_coords


def get_opts():
    parser = argparse.ArgumentParser("worldmap_v4.mosaic")

    parser.add_argument("--domcdb", type=Path)
    parser.add_argument("--regionsdb", type=Path)
    parser.add_argument("--mapdir", type=Path)

    grp_bonnie = parser.add_mutually_exclusive_group()
    grp_bonnie.add_argument("--bonniedb", type=Path)
    grp_bonnie.add_argument("--fetchbonnie", type=Path)

    _opts = parser.parse_args()

    return _opts


Coord = tuple[int, int]
DominantColorsDB: dict[Coord, dict[int, list[RGBTuple]]] = {}
RegionsDB: dict[Coord, Any] = {}


def main(domcdb: Path, regionsdb: Path, mapdir: Path):
    if not regionsdb.exists():
        raise FileNotFoundError(f"Can't find RegionsDB {regionsdb}")
    if not mapdir.exists() or not mapdir.is_dir():
        raise NotADirectoryError(f"Can't find MapsDir {mapdir}")

    if domcdb.exists():
        with domcdb.open("rb") as fin:
            DominantColorsDB = pickle.load(fin)

    with regionsdb.open("rb") as fin:
        RegionsDB = pickle.load(fin)



if __name__ == '__main__':
    opts = get_opts()
    main(**vars(opts))
