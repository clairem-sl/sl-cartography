import multiprocessing as MP
import multiprocessing.managers as MPMgrs
import multiprocessing.pool as MPPool
import pickle
import re
import signal
import sys
import time
from pathlib import Path
from typing import TypedDict, Final, cast

from PIL import Image

from sl_maptools import CoordType
from sl_maptools.image_processing import FASCIA_SIZES, RGBTuple, calculate_dominant_colors

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


class DrawJob(TypedDict):
    coord: CoordType
    dom_colors: DomColors


DrawQueue: MP.Queue
CalcCache: dict[CoordType, DomColors]


def calc_domc_init(draw_queue: MP.Queue, calc_cache: dict[CoordType, DomColors]):
    global DrawQueue, CalcCache
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    DrawQueue = draw_queue
    CalcCache = calc_cache


def calc_domc(job: tuple[CoordType, Path]) -> None | tuple[CoordType, DomColors]:
    global DrawQueue, CalcCache

    coord, fpath = job
    # noinspection PyTypeChecker
    draw_job: DrawJob = {}

    def _put():
        if DrawQueue.qsize() > 500:
            time.sleep(1)
        DrawQueue.put(draw_job)

    if coord in CalcCache:
        draw_job = {
            "coord": coord,
            "dom_colors": CalcCache[coord],
        }
        _put()
        return None

    with fpath.open("rb") as fin:
        img = Image.open(fin)
        img.load()
    domc: DomColors = {fsz: calculate_dominant_colors(img, fsz) for fsz in FASCIA_SIZES}
    draw_job = {
        "coord": coord,
        "dom_colors": domc
    }
    _put()
    return coord, domc


def make_mosaic(queue: MP.Queue, fascia_pixels: dict[int, int], patches: dict[int, dict[CoordType, Image.Image]]):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    c = 0
    while True:
        item = queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        c += 1
        job = cast(DrawJob, item)
        x, y = job["coord"]
        domc = job["dom_colors"]
        patch: dict[int, list[RGBTuple]] = {}
        for sz, colors in domc.items():
            # print(x, y, colors)
            fpx = fascia_pixels[sz]
            tsz = fpx * sz
            cx = tsz * x
            cy = tsz * (2100 - y)
            sx = sy = 0
            for col in colors:
                f_img = Image.new("RGB", (fpx, fpx), color=col)
                patches[cx + sx, cy + sy] =
                sy += fpx
                if sy >= tsz:
                    sy = 0
                    sx += fpx
            patches[sz] = patch_by_coord
        if (c % 100) == 0:
            print(f"qsize={queue.qsize()}")


def draw_mosaic(draw_queue: MP.Queue, patches_dict: dict[CoordType, dict[int, Image.Image]], fascia_pixels: dict[int, int], mapdir: Path):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        item = draw_queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        patches = dict(patches_dict)
        for sz, fpx in fascia_pixels.items():
            print(f"💾{sz}", end="", flush=True)
            sidelen = 2101 * fpx * sz
            canvas = Image.new("RGBA", (sidelen, sidelen))
            for coord, patch in patches.items():
                # print(sz, coord, end=" ", flush=True)
                canvas.paste(patch[sz], coord)
            canvas.save(mapdir / f"worldmap4_mosaic_{sz}x{sz}.png")
            print(f"🟢{sz}", end="", flush=True)


def main(workers: int = 6, no_cache: bool = False, pip_every: int = 100, save_every: int = 1000):

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
    mapfiles: list[tuple[CoordType, Path]] = sorted(mapfiles_d.items(), key=lambda c: (-c[0][1], c[0][0]))

    manager: MPMgrs.SyncManager
    with MP.Manager() as manager:

        draw_workers = 1
        draw_queue = manager.Queue()
        patches_dict = manager.dict({sz: {} for sz in FASCIA_PIXELS})
        draw_args = (draw_queue, patches_dict, FASCIA_PIXELS, MAPDIR)

        make_workers = 1
        make_queue = manager.Queue()
        make_args = (make_queue, FASCIA_PIXELS, patches_dict)

        calc_workers = workers
        calc_domc_args = (make_queue, cached_domc)

        poolc: MPPool.Pool
        poolm: MPPool.Pool
        poold: MPPool.Pool
        with (
            MP.Pool(calc_workers, initializer=calc_domc_init, initargs=calc_domc_args) as poolc,
            MP.Pool(make_workers, initializer=make_mosaic, initargs=make_args) as poolm,
            MP.Pool(draw_workers, initializer=draw_mosaic, initargs=draw_args) as poold
        ):
            try:
                for i, rslt in enumerate(poolc.imap_unordered(calc_domc, mapfiles, chunksize=10), start=1):
                    if rslt is not None:
                        coord, domc = rslt
                        cached_domc[coord] = domc
                    if (i % pip_every) == 0:
                        print(".", end="", flush=True)
                    if (i % save_every) == 0:
                        draw_queue.put(1)
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
            print(f"closed.\nEnjoining poolm (qsize={make_queue.qsize()})... ", end="", flush=True)
            poolm.close()
            make_queue.put(None)
            poolm.join()
            print("joined.\nEnjoining poold ... ", end="", flush=True)
            poold.close()
            draw_queue.put(None)
            poold.join()
            print("joined.", flush=True)



if __name__ == "__main__":
    main()
