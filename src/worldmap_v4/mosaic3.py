import argparse
import multiprocessing as MP
import multiprocessing.managers as MPMgrs
import multiprocessing.pool as MPPool
import pickle
import re
import signal
import sys
import time
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast

from PIL import Image

from sl_maptools import CoordType
from sl_maptools.image_processing import (
    FASCIA_SIZES,
    RGBTuple,
    calculate_dominant_colors,
)

# region ##### Types

DomColors = dict[int, list[RGBTuple]]

# endregion

# region ##### CONSTs

RE_MAP: Final[re.Pattern] = re.compile(r"^(\d+)-(\d+)_\d+-\d+.jpg$")

DEFA_MAPDIR: Final[Path] = Path(r"C:\Cache\SL-Carto\Maps2")
CACHE_FILE: Final[str] = "CachedDominantColors.pkl"

DEFA_CALC_WORKERS: Final[int] = max(1, MP.cpu_count() - 2)
DEFA_MAKE_WORKERS: Final[int] = 1

FASCIA_PIXELS: Final[dict[int, int]] = {
    1: 3,
    2: 3,
    3: 3,
    4: 2,
    5: 2,
}

# endregion

# region ##### CLI options


class OptionsType(Protocol):
    reset_cache: bool
    no_cache: bool
    calc_workers: int
    make_workers: int
    pip_every: int
    save_every: int
    mapdir: Path


def get_opts() -> OptionsType:
    parser = argparse.ArgumentParser("worldmap_v4.mosaic")

    cache_grp = parser.add_mutually_exclusive_group()
    cache_grp.add_argument("--reset-cache", action="store_true")
    cache_grp.add_argument("--no-cache", action="store_true")

    parser.add_argument(
        "--calc-workers", metavar="N", type=int, default=DEFA_CALC_WORKERS
    )
    parser.add_argument(
        "--make-workers", metavar="N", type=int, default=DEFA_MAKE_WORKERS
    )
    parser.add_argument("--pip-every", metavar="N", type=int, default=100)
    parser.add_argument("--save-every", metavar="N", type=int, default=2000)
    parser.add_argument("--mapdir", metavar="DIR", type=Path, default=DEFA_MAPDIR)

    _opts = parser.parse_args()
    return cast(OptionsType, _opts)


# endregion

# region ##### Worker: Dominant Color Calculator


class CalcJob(TypedDict):
    coord: CoordType
    fpath: Path


CalcCache: None | dict[CoordType, DomColors]
PatchesDict: dict[tuple[CoordType, int], list[RGBTuple]]
CollectorQueue: MP.Queue


def calc_domc_init(
    patches_dict: dict[tuple[CoordType, int], list[RGBTuple]],
    calc_cache: None | dict[CoordType, DomColors],
    coll_queue: MP.Queue,
):
    global PatchesDict, CalcCache, CollectorQueue
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    PatchesDict = patches_dict
    CalcCache = calc_cache
    CollectorQueue = coll_queue


def calc_domc(job: tuple[CoordType, Path]) -> tuple[CoordType, DomColors]:
    global PatchesDict, CalcCache
    coord, fpath = job

    # If cache is None that means we want to ignore cache
    if CalcCache is not None and coord in CalcCache:
        domc: DomColors = CalcCache[coord]
    else:
        with fpath.open("rb") as fin:
            img = Image.open(fin)
            img.load()
        domc: DomColors = {
            fsz: calculate_dominant_colors(img, fsz) for fsz in FASCIA_SIZES
        }

    rslt = coord, domc
    CollectorQueue.put(rslt)
    return rslt


# endregion

# region ##### Worker: Collector

def collector(coll_queue: MP.Queue, patches_coll: dict[tuple[CoordType, int], list[RGBTuple]], coll_lock: MP.RLock):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        item = coll_queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        coord, domc = cast(tuple[CoordType, DomColors], item)
        with coll_lock:
            for sz, colors in domc.items():
                patches_coll[coord, sz] = colors

# endregion

# region ##### Worker: Mosaic Maker


def make_mosaic(
    queue: MP.Queue,
    patches_coll: dict[tuple[CoordType, int], list[RGBTuple]],
    coll_lock: MP.RLock,
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
        with coll_lock:
            for k, v in dict(patches_coll).items():
                coord, sz = k
                if sz not in patches_bysz:
                    continue
                patches_bysz[sz][coord] = v

        for sz, patches in patches_bysz.items():
            print(f"💾{sz}", end="", flush=True)
            fpx = FASCIA_PIXELS[sz]
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


# endregion


def main(opts: OptionsType):
    cached_domc: dict[CoordType, DomColors] = {}
    cache_path = opts.mapdir / CACHE_FILE
    if not opts.reset_cache:
        if cache_path.exists():
            try:
                with cache_path.open("rb") as fin:
                    cached_domc.update(pickle.load(fin))
            except EOFError:
                pass
    print(f"Cached Dominant Colors = {len(cached_domc)}")
    if opts.no_cache:
        print("  ^^ Will be ignored! (But new ones will still be saved)")

    mapfiles_d: dict[CoordType, Path] = {}
    for mf in sorted(opts.mapdir.glob("*.jpg"), reverse=True):
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
        patches_coll = manager.dict()
        coll_lock = manager.RLock()

        make_workers = opts.make_workers
        make_queue = manager.Queue()
        make_args = (make_queue, patches_coll, coll_lock, opts.mapdir)

        coll_queue = manager.Queue()
        coll_args = (coll_queue, patches_coll, coll_lock)

        calc_workers = opts.calc_workers
        calc_domc_args = (patches_coll, None if opts.no_cache else cached_domc, coll_queue)

        poolc: MPPool.Pool
        pool_coll: MPPool.Pool
        poolm: MPPool.Pool
        with (
            MP.Pool(
                calc_workers, initializer=calc_domc_init, initargs=calc_domc_args
            ) as poolc,
            MP.Pool(1, initializer=collector, initargs=coll_args) as pool_coll,
            MP.Pool(make_workers, initializer=make_mosaic, initargs=make_args) as poolm,
        ):
            try:
                for i, rslt in enumerate(
                    poolc.imap_unordered(calc_domc, mapfiles, chunksize=10), start=1
                ):
                    make_recently_triggered = False
                    coord, domc = rslt
                    cached_domc[coord] = domc
                    if (i % opts.pip_every) == 0:
                        print(".", end="", flush=True)
                    if (i % opts.save_every) == 0:
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
                f"joined.\nEnjoining pool_coll (qsize={make_queue.qsize()})... ",
                end="",
                flush=True,
            )
            pool_coll.close()
            coll_queue.put(None)
            pool_coll.join()
            print(
                f"joined.\nEnjoining poolm (qsize={make_queue.qsize()})... ",
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
    options = get_opts()
    main(options)
