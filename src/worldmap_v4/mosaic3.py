import multiprocessing as MP
import multiprocessing.managers as MPMgrs
import multiprocessing.pool as MPPool
import pickle
import re
import signal
import sys
import time
from pathlib import Path
from typing import Final, TypedDict

from PIL import Image

from sl_maptools import CoordType
from sl_maptools.image_processing import (
    FASCIA_SIZES,
    RGBTuple,
    calculate_dominant_colors,
)

RE_MAP = re.compile(r"^(\d+)-(\d+)_\d+-\d+.jpg$")

MAPDIR: Final[Path] = Path(r"C:\Cache\SL-Carto\Maps2")
CACHE_FILE: Final[str] = "CachedDominantColors.pkl"

FASCIA_PIXELS: Final[dict[int, int]] = {
    1: 3,
    2: 3,
    3: 3,
    4: 2,
    5: 2,
}


class CalcJob(TypedDict):
    coord: CoordType
    fpath: Path


DomColors = dict[int, list[RGBTuple]]


CalcCache: dict[CoordType, DomColors]
PatchesDict: dict[tuple[CoordType, int], list[RGBTuple]]


def calc_domc_init(
    patches_dict: dict[tuple[CoordType, int], list[RGBTuple]],
    calc_cache: dict[CoordType, DomColors],
):
    global PatchesDict, CalcCache
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    PatchesDict = patches_dict
    CalcCache = calc_cache


def calc_domc(job: tuple[CoordType, Path]) -> tuple[CoordType, DomColors]:
    global PatchesDict, CalcCache
    coord, fpath = job

    if coord in CalcCache:
        domc: DomColors = CalcCache[coord]
    else:
        with fpath.open("rb") as fin:
            img = Image.open(fin)
            img.load()
        domc: DomColors = {
            fsz: calculate_dominant_colors(img, fsz) for fsz in FASCIA_SIZES
        }

    for sz, colors in domc.items():
        PatchesDict[coord, sz] = colors

    return coord, domc


def make_mosaic(
    queue: MP.Queue,
    fascia_pixels: dict[int, int],
    patches_dict: dict[tuple[CoordType, int], list[RGBTuple]],
    mapdir: Path,
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        item = queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        if not isinstance(item, tuple):
            continue

        assert isinstance(item, tuple)
        patches_bysz: dict[int, dict[CoordType, list[RGBTuple]]] = {
            sz: {} for sz in item
        }
        for k, v in dict(patches_dict).items():
            coord, sz = k
            if sz not in patches_bysz:
                continue
            patches_bysz[sz][coord] = v

        for sz, patches in patches_bysz.items():
            print(f"💾{sz}", end="", flush=True)
            fpx = fascia_pixels[sz]
            tsz = fpx * sz
            sidelen = 2101 * tsz
            canvas = Image.new("RGBA", (sidelen, sidelen))
            for coord, colors in patches.items():
                x, y = coord
                cx = tsz * x
                cy = tsz * (2100 - y)
                sx = sy = 0
                for col in colors:
                    f_img = Image.new("RGB", (fpx, fpx), color=col)
                    canvas.paste(f_img, (cx + sx, cy + sy))
                    sy += fpx
                    if sy >= tsz:
                        sy = 0
                        sx += fpx
            canvas.save(mapdir / f"worldmap4_mosaic_{sz}x{sz}.png")
            print(f"🟢{sz}", end="", flush=True)


def main(
    workers: int = 6,
    no_cache: bool = False,
    pip_every: int = 100,
    save_every: int = 1000,
):
    cached_domc: dict[CoordType, DomColors] = {}
    cache_path = MAPDIR / CACHE_FILE
    if not no_cache and cache_path.exists():
        try:
            with cache_path.open("rb") as fin:
                cached_domc.update(pickle.load(fin))
        except EOFError:
            pass
    print(f"Cached Dominant Colors = {len(cached_domc)}")

    mapfiles_d: dict[CoordType, Path] = {}
    for mf in sorted(MAPDIR.glob("*.jpg"), reverse=True):
        if (m := RE_MAP.match(mf.name)) is None:
            continue
        coord = int(m.group(1)), int(m.group(2))
        if coord in mapfiles_d:
            continue
        mapfiles_d[coord] = mf
    if len(mapfiles_d) == 0:
        print("ERROR: No mapfiles!", file=sys.stderr)
        sys.exit(1)
    mapfiles: list[tuple[CoordType, Path]] = sorted(
        mapfiles_d.items(), key=lambda c: (-c[0][1], c[0][0])
    )

    start = time.monotonic()
    manager: MPMgrs.SyncManager
    with MP.Manager() as manager:
        patches_dict = manager.dict()

        make_workers = 1
        make_queue = manager.Queue()
        make_args = (make_queue, FASCIA_PIXELS, patches_dict, MAPDIR)

        calc_workers = workers
        calc_domc_args = (patches_dict, cached_domc)

        poolc: MPPool.Pool
        poolm: MPPool.Pool
        with (
            MP.Pool(
                calc_workers, initializer=calc_domc_init, initargs=calc_domc_args
            ) as poolc,
            MP.Pool(make_workers, initializer=make_mosaic, initargs=make_args) as poolm,
        ):
            try:
                for i, rslt in enumerate(
                    poolc.imap_unordered(calc_domc, mapfiles, chunksize=10), start=1
                ):
                    make_recently_triggered = False
                    coord, domc = rslt
                    cached_domc[coord] = domc
                    if (i % pip_every) == 0:
                        print(".", end="", flush=True)
                    if (i % save_every) == 0:
                        make_queue.put(tuple(FASCIA_SIZES))
                        make_recently_triggered = True
                if not make_recently_triggered:
                    make_queue.put(tuple(FASCIA_SIZES))
            except KeyboardInterrupt:
                print("\nUser request abort...", flush=True)
            finally:
                print(f"Cached Dominant Colors is now {len(cached_domc)}, ", end="")
                with cache_path.open("wb") as fout:
                    pickle.dump(cached_domc, fout)
                print(f"saved to {cache_path}")

            print("Enjoining poolc ... ", end="", flush=True)
            poolc.close()
            poolc.terminate()
            poolc.join()
            print(
                f"closed.\nEnjoining poolm (qsize={make_queue.qsize()})... ",
                end="",
                flush=True,
            )
            poolm.close()
            make_queue.put(None)
            poolm.join()
            print("joined.", flush=True)

    elapsed = time.monotonic() - start
    print(f"Done in {elapsed:_.2f} seconds.")


if __name__ == "__main__":
    main()
