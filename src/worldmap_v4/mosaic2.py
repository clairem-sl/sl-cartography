import argparse
import multiprocessing as MP
import multiprocessing.pool as MPPool
import pickle
import re
import signal
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from sl_maptools.image_processing import (
    FASCIA_SIZES,
    RGBTuple,
    calculate_dominant_colors,
)
from worldmap_v4 import get_bonnie_coords


CoordType = tuple[int, int]


RE_REGMAP_FN: re.Pattern = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_\d+-\d+.jpg$")


DEFA_REGIONSDB = Path(r"C:\Cache\SL-Carto\RegionsDB.pkl")
DEFA_MAPDIR = Path(r"C:\Cache\SL-Carto\Maps2")
DEFA_CACHE = DEFA_MAPDIR / "DominantColors.pkl"


def get_opts():
    parser = argparse.ArgumentParser("worldmap_v4.mosaic")

    parser.add_argument("--regionsdb", type=Path, default=DEFA_REGIONSDB)
    parser.add_argument("--mapdir", type=Path, default=DEFA_MAPDIR)
    parser.add_argument("--tilesize", metavar="N", type=int, default=9)
    parser.add_argument("--workers", metavar="N", type=int, default=max(1, MP.cpu_count() - 2))
    parser.add_argument("--cachefile", type=Path, default=DEFA_CACHE)
    parser.add_argument("--no-cache", action="store_true")

    grp_bonnie = parser.add_mutually_exclusive_group()
    grp_bonnie.add_argument("--bonniedb", type=Path)
    grp_bonnie.add_argument("--fetchbonnie", action="store_true")

    _opts = parser.parse_args()

    return _opts


OrigSigINT: signal.Handlers = signal.getsignal(signal.SIGINT)
DominantColorsDB: dict[CoordType, dict[int, list[RGBTuple]]] = {}
RegionsDB: dict[CoordType, Any] = {}
MapFiles: dict[CoordType, Path] = {}
AbortRequested = MP.Event()


def sigint_handler(_, __):
    global AbortRequested
    if not AbortRequested.is_set():
        print("\n### USER INTERRUPT ###")
        AbortRequested.set()


WorkerCachedDomC: dict[Path, dict[int, list[RGBTuple]]]


def calc_domc_init(cached_domc: dict[Path, dict[int, list[RGBTuple]]]):
    global WorkerCachedDomC
    WorkerCachedDomC = cached_domc
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def calc_domc(job: tuple[CoordType, Path]):
    try:
        coord, mapfile = job
        domc: dict[int, list[RGBTuple]]
        if WorkerCachedDomC and (domc := WorkerCachedDomC.get(mapfile)) is not None:
            return coord, mapfile, domc
        with mapfile.open("rb") as fin:
            img = Image.open(fin)
            img.load()
        domc = {fsz: calculate_dominant_colors(img, fsz) for fsz in FASCIA_SIZES}
        return coord, mapfile, domc
    except KeyboardInterrupt:
        pass


def make_mosaic(data: dict[CoordType, list[RGBTuple]], tilesize: int, max_coords: CoordType):
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


def main(
    regionsdb: Path,
    mapdir: Path,
    bonniedb: Path,
    fetchbonnie: bool,
    tilesize: int,
    workers: int,
    cachefile: Path,
    no_cache: bool,
):
    global DominantColorsDB, RegionsDB, MapFiles

    if not regionsdb.exists():
        raise FileNotFoundError(f"Can't find RegionsDB {regionsdb}")
    if not mapdir.exists() or not mapdir.is_dir():
        raise NotADirectoryError(f"Can't find MapsDir {mapdir}")

    with regionsdb.open("rb") as fin:
        RegionsDB.update(pickle.load(fin))
    coords_to_process = set(RegionsDB.keys())

    bonnie_coords = get_bonnie_coords(bonniedb, fetchbonnie)
    print(" done.")
    coords_to_process.intersection_update(bonnie_coords)

    cached_domc: dict[Path, dict[int, list[RGBTuple]]]
    if not no_cache and cachefile.exists():
        with cachefile.open("rb") as fin:
            cached_domc = pickle.load(fin)
        for fp in sorted(cached_domc.keys()):
            if not fp.exists():
                del cached_domc[fp]
        print(f"Cached Dominant Colors loaded, {len(cached_domc)} regions was cached.")
    else:
        cached_domc = {}
        print("Cached Dominant Colors not loaded (but will be saved).")

    _mapfiles = {}
    for fp in sorted(mapdir.glob("*.jpg"), reverse=True):
        if (m := RE_REGMAP_FN.match(fp.name)) is None:
            continue
        co = (int(m.group("x")), int(m.group("y")))
        if co in coords_to_process and co not in _mapfiles:
            _mapfiles[co] = fp
    MapFiles = {co: mf for co, mf in sorted(_mapfiles.items(), key=lambda v: (v[0][1], v[0][0]))}
    print(f"{len(MapFiles)} regions to mosaicize.")

    world_domc: dict[int, dict[CoordType, list[RGBTuple]]] = {n: {} for n in FASCIA_SIZES}

    print(f"Calculating dominant colors ", end="", flush=True)
    signal.signal(signal.SIGINT, sigint_handler)
    pool: MPPool.Pool
    i = 0
    with MP.Pool(workers, initializer=calc_domc_init, initargs=(cached_domc,)) as pool:
        for i, result in enumerate(pool.imap_unordered(calc_domc, MapFiles.items()), start=1):
            coord, mapfile, domc = result
            for fsz, cols in domc.items():
                world_domc[fsz][coord] = cols
            cached_domc[mapfile] = domc
            with cachefile.open("wb") as fout:
                pickle.dump(cached_domc, fout)
            if (i % 100) == 0:
                print(".", end="", flush=True)
            if AbortRequested.is_set():
                print(f"User aborted.\nResults so far ({i} regions) are stored in {cachefile}.")
                sys.exit(0)
    signal.signal(signal.SIGINT, OrigSigINT)
    print("✅")

    for fsz in FASCIA_SIZES:
        print(f"Making {fsz}x{fsz} mosaic ... ", end="", flush=True)
        make_mosaic(world_domc[fsz], tilesize, (2100, 2100))


if __name__ == "__main__":
    opts = get_opts()
    main(**vars(opts))
