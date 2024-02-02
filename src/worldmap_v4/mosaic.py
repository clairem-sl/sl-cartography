# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import multiprocessing as MP
import multiprocessing.managers as MPMgrs
import multiprocessing.pool as MPPool
import pickle
import re
import signal
import time
from pathlib import Path
from typing import Final, NamedTuple, Optional, Protocol, TypedDict, cast

from PIL import Image, UnidentifiedImageError

from sl_maptools import CoordType, RegionsDBRecord, inventorize_maps_all
from sl_maptools.image_processing import (
    FASCIA_SIZES,
    RGBTuple,
    calculate_dominant_colors,
)
from sl_maptools.utils import ConfigReader, SLMapToolsConfig, make_backup
from sl_maptools.validator import get_bonnie_coords

# region ##### Types

DomColors = dict[int, list[RGBTuple]]

# endregion

# region ##### CONSTs
Config: SLMapToolsConfig = ConfigReader("config.toml")

RE_MAP: Final[re.Pattern] = re.compile(r"^(\d+)-(\d+)_\d+-\d+.jpg$")

DEFA_CALC_WORKERS: Final[int] = max(1, MP.cpu_count() - 2) * 2
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
    """Represents options extracted from CLI"""

    calc_workers: int
    make_workers: int
    pip_every: int
    stats_every_min: int
    save_every: int
    no_bonnie: bool
    final_only: bool


def get_opts() -> OptionsType:
    """Get options from CLI"""
    parser = argparse.ArgumentParser("worldmap_v4.mosaic")

    parser.add_argument("--calc-workers", metavar="N", type=int, default=DEFA_CALC_WORKERS)
    parser.add_argument("--make-workers", metavar="N", type=int, default=DEFA_MAKE_WORKERS)
    parser.add_argument("--pip-every", metavar="N", type=int, default=100)
    parser.add_argument("--save-every", metavar="N", type=int, default=2000)
    parser.add_argument("--stats-every-min", metavar="N", type=int, default=15)
    parser.add_argument("--final-only", action="store_true")

    bonnie_grp = parser.add_mutually_exclusive_group()
    bonnie_grp.add_argument(
        "--no-bonnie", action="store_true", default=False, help="Do not validate against BonnieBots DB"
    )

    _opts = parser.parse_args()
    return cast(OptionsType, _opts)


# endregion

# region ##### Worker: Dominant Color Calculator


class CalcJob(TypedDict):
    """Represents a job containing coordinates and a map tile"""

    coord: CoordType
    fpath: Path


PatchesDict: dict[tuple[CoordType, int], list[RGBTuple]]
CollectorQueue: MP.Queue


def calc_domc_init(
    patches_dict: dict[tuple[CoordType, int], list[RGBTuple]],
    coll_queue: MP.Queue,
) -> None:
    """Initializer for domc calculator workers"""
    global PatchesDict, CollectorQueue  # noqa: PLW0603
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    PatchesDict = patches_dict
    CollectorQueue = coll_queue


CalcResultType = tuple[CoordType, Path, DomColors]


def calc_domc(job: tuple[CoordType, Path]) -> CalcResultType | None:
    """A worker that calculates dominant color for a job"""
    coord, fpath = job
    if not fpath.exists() or not fpath.is_file():
        return None

    try:
        with Image.open(fpath) as img:
            img.load()
            domc: DomColors = {fsz: calculate_dominant_colors(img, fsz) for fsz in FASCIA_SIZES}
    except UnidentifiedImageError:
        fpath.unlink()
        return None

    rslt = coord, fpath, domc
    CollectorQueue.put(rslt)
    return rslt


# endregion

# region ##### Worker: Collector


def collector(
    coll_queue: MP.Queue,
    patches_coll: dict[tuple[CoordType, int], list[RGBTuple]],
    coll_lock: MP.RLock,
) -> None:
    """Gather results of domc calculation into a collection"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        item = coll_queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        coord, _, domc = cast(CalcResultType, item)
        with coll_lock:
            for sz, colors in domc.items():
                patches_coll[coord, sz] = colors


# endregion

# region ##### Worker: Mosaic Maker


class MakerParams(NamedTuple):
    """Parameters passed to the make_mosaic worker"""
    worker_state: dict[str, str]
    queue: MP.Queue
    patches_coll: dict[tuple[CoordType, int], list[RGBTuple]]
    coll_lock: MP.RLock
    outdir: Path


def make_mosaic(params: MakerParams) -> None:
    """
    Gather dominant colors and create the mosaic maps.
    You shouldn't launch too many of this worker, since this worker is not the bottleneck.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    def _state(state: str) -> None:
        params.worker_state["maker"] = state

    while True:
        _state("idle")
        item = params.queue.get()
        if item is None:
            break
        if item is Ellipsis:
            continue

        if not isinstance(item, tuple):
            continue

        _state("got_job")
        assert isinstance(item, tuple)
        patches_bysz: Optional[dict[int, dict[CoordType, list[RGBTuple]]]] = {sz: {} for sz in item}
        with params.coll_lock:
            _state("transform")
            for k, v in dict(params.patches_coll).items():
                coord, sz = k
                if sz not in patches_bysz:
                    continue
                patches_bysz[sz][coord] = v

        for sz, patches in patches_bysz.items():
            _state(f"make_{sz}_canvas")
            print(f"⏺{sz}", end="", flush=True)
            fpx = FASCIA_PIXELS[sz]
            fbox = fpx, fpx
            tsz = fpx * sz
            sidelen = 2101 * tsz
            canvas = Image.new("RGBA", (sidelen, sidelen))
            _state(f"make_{sz}_patches")
            for coord, colors in patches.items():
                x, y = coord
                cx = tsz * x
                cy = tsz * (2100 - y)
                sx = sy = 0
                for col in colors:
                    canvas.paste(Image.new("RGB", fbox, color=col), (cx + sx, cy + sy))
                    sy += fpx
                    if sy >= tsz:
                        sy = 0
                        sx += fpx
            _state(f"save_{sz}")
            canvas.save(params.outdir / f"worldmap4_mosaic_{sz}x{sz}.png")
            canvas.close()
            print(f"💾{sz}", end="", flush=True)
        # noinspection PyUnusedLocal
        canvas = None
        # noinspection PyUnusedLocal
        patches_bysz = None

    _state("ended")


# endregion


def main(opts: OptionsType) -> None:  # noqa: D103
    mosaic_dir = Path(Config.mosaic.dir)

    domc_db: dict[CoordType, dict[Path, DomColors]] = {}
    domc_db_path = mosaic_dir / Config.mosaic.domc_db
    if domc_db_path.exists():
        try:
            with domc_db_path.open("rb") as fin:
                domc_db.update(pickle.load(fin))  # noqa: S301
        except EOFError:
            pass
    print(f"Cached Dominant Colors = {len(domc_db):_} coords ({sum(map(len, domc_db.values())):_} files)")

    mapfiles_d: dict[CoordType, list[Path]] = inventorize_maps_all(Config.maps.dir)
    #
    regdb_p = Path(Config.names.dir) / Config.names.db
    regions_db: dict[CoordType, RegionsDBRecord] = {}
    if regdb_p.exists():
        with regdb_p.open("rb") as fin:
            regions_db = pickle.load(fin)  # noqa: S301
    if regions_db:
        for k in list(mapfiles_d.keys()):
            if k not in regions_db or regions_db[k]["current_name"] == "":
                del mapfiles_d[k]
    #
    if not opts.no_bonnie:
        bonnie_coords = get_bonnie_coords(Config.bonnie)
        for k in list(mapfiles_d.keys()):
            if k not in bonnie_coords:
                del mapfiles_d[k]

    # fmt: off
    # Grab only files that are not yet analyzed
    mapfiles: list[tuple[CoordType, Path]] = [
        (co, mapf)
        for co, mapfl in mapfiles_d.items()
        for mapf in mapfl
        if mapf not in domc_db.get(co, {})
    ]
    # fmt: on

    # Sort by CoordType[0] row[1] descending (-)
    # then by CoordType[0] col[0] ascending
    # then by Filepath[1] ascending
    mapfiles.sort(key=lambda c: (-c[0][1], c[0][0], c[1]))
    print(
        f"\n{len(mapfiles):_} files to analyze, {len(mapfiles_d):_} regions to mosaicize."
        f"\nStarting up Mosaic-Making Engine ({opts.calc_workers} calc, {opts.make_workers} make),"
        f"\nOne dot '.' represents {opts.pip_every} regions processed."
    )

    latest_domc: dict[CoordType, DomColors] = {
        # data.items() will be a sequence of (path, domcolors)
        # If we sort, the newest file (latest timestamp) will be at end, so [-1]
        # Then we get the domcolors component of the tuple [1]
        co: sorted(data.items())[-1][1]
        for co, data in domc_db.items()
        if co in mapfiles_d
    }

    for sz in FASCIA_PIXELS:
        targ = mosaic_dir / f"worldmap4_mosaic_{sz}x{sz}.png"
        if targ.exists():
            make_backup(targ)

    last_stat = start = time.monotonic()
    last_fin = 0
    stats_every_sec = opts.stats_every_min * 60
    manager: MPMgrs.SyncManager
    with MP.Manager() as manager:
        patches_coll = manager.dict({(co, sz): vals for co, domc in latest_domc.items() for sz, vals in domc.items()})
        coll_lock = manager.RLock()

        maker_workers = opts.make_workers
        maker_states = manager.dict()
        maker_queue = manager.Queue()
        # make_args = (maker_states, maker_queue, patches_coll, coll_lock, opts.outdir)
        make_args = MakerParams(
            worker_state=cast(dict, maker_states),
            queue=maker_queue,
            patches_coll=cast(dict, patches_coll),
            coll_lock=coll_lock,
            outdir=mosaic_dir,
        )

        coll_queue = manager.Queue(maxsize=(opts.save_every * 2))
        coll_args = (coll_queue, patches_coll, coll_lock)

        calc_workers = opts.calc_workers
        calc_domc_args = (
            patches_coll,
            coll_queue,
        )

        pool_calc: MPPool.Pool
        pool_coll: MPPool.Pool
        pool_maker: MPPool.Pool
        with (
            MP.Pool(calc_workers, initializer=calc_domc_init, initargs=calc_domc_args) as pool_calc,
            MP.Pool(1, initializer=collector, initargs=coll_args) as pool_coll,
            MP.Pool(maker_workers, initializer=make_mosaic, initargs=(make_args,)) as pool_maker,
        ):
            try:
                for i, rslt in enumerate(pool_calc.imap_unordered(calc_domc, mapfiles, chunksize=10), start=1):
                    if rslt is None:
                        continue
                    make_recently_triggered = False
                    coord, fpath, domc = rslt
                    domc_db.setdefault(coord, {})[fpath] = domc
                    if (i % opts.pip_every) == 0:
                        print(".", end="", flush=True)
                    if (stat_passed := (time.monotonic() - last_stat)) >= stats_every_sec:
                        stat_rate = (i - last_fin) / stat_passed
                        print(f"\n {i:_}/{len(mapfiles):_} processed so far ({stat_rate:_.2f} per second)", flush=True)
                        last_fin = i
                        last_stat = time.monotonic()
                    if (
                        not opts.final_only
                        and (i % opts.save_every) == 0
                        and any(state == "idle" for state in maker_states.values())
                    ):
                        maker_queue.put(tuple(FASCIA_SIZES))
                        print("🏀", end="", flush=True)
                        make_recently_triggered = True
                    if (i % opts.save_every) == 2:  # noqa: PLR2004
                        print(f"q={coll_queue.qsize()}", end="", flush=True)
                while not all(s == "idle" for s in maker_states.values()):
                    print("-", end="", flush=True)
                    time.sleep(5)
                while not coll_queue.empty():
                    print("=", end="", flush=True)
                    time.sleep(1)
                if not make_recently_triggered:
                    print("\nFINAL mosaic making started!", end=" ", flush=True)
                    maker_queue.put(tuple(FASCIA_SIZES))
                    time.sleep(1)
                while any(s != "idle" for s in maker_states.values()):
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nUser request abort...", flush=True)
            finally:
                orig_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
                print(
                    f"\nCached Dominant Colors is now "
                    f"{len(domc_db)} coords ({sum(map(len, domc_db.values()))} files), ",
                    end="",
                )
                make_backup(domc_db_path)
                # Sort so it's right and nice order
                sorted_cache = {}
                # By row ascending, then by col ascending ...
                for co, data in sorted(domc_db.items(), key=lambda c: (c[0][1], c[0][0])):
                    inner = {}
                    # ... then by filepath ascending
                    for fp, domc in sorted(data.items()):
                        inner[fp] = domc
                    sorted_cache[co] = inner
                with domc_db_path.open("wb") as fout:
                    pickle.dump(sorted_cache, fout)
                print(f"saved to {domc_db_path}", flush=True)
                signal.signal(signal.SIGINT, orig_sigint)

            print("Enjoining pool_calc ... ", end="", flush=True)
            pool_calc.close()
            pool_calc.terminate()
            pool_calc.join()
            print(
                "joined.\nEnjoining pool_coll ... ",
                end="",
                flush=True,
            )
            pool_coll.close()
            coll_queue.put(None)
            pool_coll.join()
            print(
                "joined.\nEnjoining pool_maker ... ",
                end="",
                flush=True,
            )
            pool_maker.close()
            for s in maker_states.values():
                if s != "ended":
                    maker_queue.put(None)
            pool_maker.join()
            print("joined.", flush=True)

    elapsed = time.monotonic() - start
    print(f"Done in {elapsed:_.2f} seconds.")


if __name__ == "__main__":
    options = get_opts()
    main(options)
