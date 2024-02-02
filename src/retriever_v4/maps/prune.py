# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import multiprocessing as MP
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

import numpy as np
from PIL import Image, UnidentifiedImageError
from skimage.metrics import mean_squared_error as mse
from skimage.metrics import structural_similarity as ssim

from sl_maptools import inventorize_maps_all
from sl_maptools.utils import ConfigReader

if TYPE_CHECKING:
    from multiprocessing.pool import Pool as MPPool

    from sl_maptools import CoordType

RE_MAPTILE_FILE = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_(?P<ts>[^.]+)\.jpe?g$")

SSIM_THRESHOLD: Final[float] = 0.895
MSE_THRESHOLD: Final[float] = 0.01

Config = ConfigReader("config.toml")


class PruneOptions(Protocol):
    """Represents the options extracted from CLI"""

    mapdir: Path


def get_options() -> PruneOptions:
    """Get options from CLI"""
    parser = argparse.ArgumentParser("retriever_v4.maps.prune")
    parser.add_argument("mapdir", type=Path, nargs="?", default=Path(Config.maps.dir))
    _opts = parser.parse_args()
    return cast(PruneOptions, _opts)


@dataclass
class Thresholds:
    """Represents thresholds to determine similarity"""

    MSE: float
    SSIM: float


def do_prune(
    filelist: list[Path],
    *,
    thresholds: Thresholds,
    quiet: bool = False,
) -> list[Path]:
    """
    :param filelist: List of Path, sorted ascending by date of retrieval (latest == last)
    :param thresholds: Thresholds for MSE and SSIM
    :param quiet: If True (default), do not print pips upon deletion
    """
    flist = filelist.copy()
    f1: Path = flist.pop()
    while flist:
        try:
            with Image.open(f1):
                break
        except UnidentifiedImageError:
            if f1.is_file():
                f1.unlink()
            f1 = flist.pop()
    else:
        # We'll go here if flist is empty. Which happens only in 2 circumstances:
        # - Either filelist contains just one element, f1; or
        # - All files are corrupt except the last one. We assume the last one is not corrupt.
        return [f1]

    with Image.open(f1) as im1:
        # noinspection PyTypeChecker
        f1_arr = np.asarray(im1.convert("L"))
        f2: Path
        while flist:
            do_delete = False
            try:
                with Image.open(f2 := flist.pop()) as im2:
                    # noinspection PyTypeChecker
                    f2_arr = np.asarray(im2.convert("L"))
                    # Image similarity test using Mean Squared Error and Structural Similarity Index,
                    # see https://pyimagesearch.com/2014/09/15/python-compare-two-images/
                    mse_result = mse(f1_arr, f2_arr)
                    if mse_result < thresholds.MSE:
                        do_delete = True
                    else:
                        ssim_result = ssim(f1_arr, f2_arr)
                        if ssim_result > thresholds.SSIM:
                            do_delete = True
                    if do_delete:
                        if not quiet:
                            print("❌", end="", flush=True)
                        f2.unlink()
                    else:
                        # Exit immediately once we found a non-similar image
                        flist.append(f2)
                        break
            except UnidentifiedImageError:
                if f2.is_file():
                    f2.unlink()
            except FileNotFoundError:
                pass
    flist.append(f1)
    return flist


def prune_job(job: tuple) -> list[Path]:
    """Unmarshal a job tuple into proper params for do_prune"""
    if len(job) == 2:  # noqa: PLR2004
        return do_prune(job[0], thresholds=job[1])
    return do_prune(job[0], thresholds=job[1], quiet=job[2])


def prune(mapfiles_bycoord: dict[CoordType, list[Path]], quiet: bool = False) -> tuple[int, int]:
    """Perform pruning of map files"""
    thresholds = Thresholds(MSE=MSE_THRESHOLD, SSIM=SSIM_THRESHOLD)

    total = 0
    jobs: list[tuple[list[Path], Thresholds, bool]] = []
    for maptiles in mapfiles_bycoord.values():
        if len(maptiles) > 1:
            total += len(maptiles)
            jobs.append((maptiles, thresholds, quiet))
    print(f"Files to process: {total}")

    count = 0
    pool: MPPool
    with MP.Pool() as pool:
        for i, rslt in enumerate(pool.imap_unordered(prune_job, jobs, chunksize=10), start=1):
            if (i % 100) == 0:
                print(".", end="", flush=True)
            count += len(rslt)
        pool.close()
        print("\nWaiting for workers to join ... ", end="", flush=True)
        pool.join()
        print("joined.")

    return total, count


def main(opts: PruneOptions) -> None:  # noqa: D103
    print(f"Pruning {opts.mapdir}")
    start = time.monotonic()
    total, count = prune(inventorize_maps_all(opts.mapdir))
    elapsed = time.monotonic() - start
    print(f"{total - count} files pruned in {elapsed:_.2f} seconds.")


if __name__ == "__main__":
    options = get_options()
    main(options)
