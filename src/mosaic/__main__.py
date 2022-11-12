# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# fmt: off
# isort: off
import sys
import platform
import asyncio
# uvloop only works with CPython on Linux
if platform.system() == "Linux" and platform.python_implementation() == "CPython":
    # noinspection PyPackageRequirements
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
else:
    uvloop = None
# isort: on
# fmt: on

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path
from pprint import PrettyPrinter
from typing import Callable, FrozenSet, Set, Union

import appdirs
import httpx

from mosaic.builder import build_mosaic
from mosaic.progress import MosaicProgress
from mosaic.tiles_processors import TileProcessorGang
from sl_maptools import MapCoord, MapTile
from sl_maptools.fetcher import MapFetcher
from sl_maptools.utils import make_backup

X_MIN_DEFA = 0
X_MAX_DEFA = 2000
Y_MIN_DEFA = 0
Y_MAX_DEFA = 2000

TOT_WIDTH = 2001
TOT_HEIGHT = 2001

SAVE_DIR = Path(r"~\Pictures\SLMap").expanduser().absolute()

DEFA_NIGHTLIGHTS = "world-nightlights-2.png"
DEFA_MOSAIC = "world-mosaic-2.png"

STATE_DIR = Path(appdirs.site_data_dir("sl-cartography"))
PROGRESS_FILE = STATE_DIR / "mosaic_progress_2.msgp"
DEFA_WORKERS = 10

# noinspection PySetFunctionToLiteral
FORCE_REDO_ROWS = set([])


@dataclass(frozen=True)
class RunParameters:
    xmin: int = X_MIN_DEFA
    xmax: int = X_MAX_DEFA
    ymin: int = Y_MIN_DEFA
    ymax: int = Y_MAX_DEFA
    redo_rows: Set[int] = field(default_factory=set)
    refresh: bool = False
    backup: int = 2
    nightlights_name: str = DEFA_NIGHTLIGHTS
    mosaic_name: str = DEFA_MOSAIC


async def fetch_world(
    x_min: int,
    x_max: int,
    y_min: int,
    y_max: int,
    tile_callback: Callable[[Union[MapTile, str]], None],
    force_rows: FrozenSet[int] = None,
    conn_limit: int = 20,
    keepalive_limit: int = 20,
    progress: MosaicProgress = None,
    err_callback: Callable[[str], None] = None,
):
    print(f"Fetching world tiles ({x_min}, {y_max})..({x_max}, {y_min})...")
    if progress is None:
        progress = MosaicProgress()

    try:
        limits = httpx.Limits(
            max_connections=conn_limit, max_keepalive_connections=keepalive_limit
        )
        async with httpx.AsyncClient(limits=limits, http2=True) as client:
            map_fetcher = MapFetcher(a_session=client)
            await map_fetcher.async_get_area(
                MapCoord(x_min, y_max),
                MapCoord(x_max, y_min),
                tile_callback=tile_callback,
                force_rows=force_rows,
                progress=progress,
                err_callback=err_callback,
            )
    except KeyboardInterrupt:
        pass
    finally:
        pass


def main(
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
    tot_width: int,
    tot_height: int,
    refresh: bool,
    redo_rows: Set[int] = False,
    backup_level: int = 3,
    nightlights_name: str = DEFA_NIGHTLIGHTS,
    mosaic_name: str = DEFA_MOSAIC,
    workers: int = DEFA_WORKERS,
):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Progress file is: {PROGRESS_FILE} {'(exists)' if PROGRESS_FILE.exists() else '(new)'}"
    )
    print("Doing backup of progress statefile...")
    make_backup(PROGRESS_FILE, backup_level)

    progress = MosaicProgress.new_from_path(PROGRESS_FILE, missing_ok=True)

    if refresh:
        print("--refresh specified, forgetting all seen tiles")
        progress.seen.clear()

    print(
        f"Total progress so far: {len(progress.seen)} coords, {len(progress.regions)} regions"
    )

    print("Preparing workers ... ", end="", flush=True)
    work_force = TileProcessorGang(workers, progress, PROGRESS_FILE)
    work_force.prime()

    print(f"\nWaiting for {workers} workers to be ready...")
    work_force.wait_ready()

    start_t = time.monotonic()

    rows_to_force = frozenset(FORCE_REDO_ROWS | progress.last_fail_rows | redo_rows)
    print(f"These rows will be forced: {sorted(rows_to_force)}", flush=True)
    for _ in range(0, 5):
        print(".", end="", flush=True)
        time.sleep(1.0)
    print()

    try:
        asyncio.run(
            fetch_world(
                xmin,
                xmax,
                ymin,
                ymax,
                tile_callback=work_force.mp_tilequeue.put,
                force_rows=rows_to_force,
                progress=progress,
                conn_limit=20,
                keepalive_limit=20,
                err_callback=work_force.mpm_errmessq.put,
            )
        )
        elapsed_t = time.monotonic() - start_t
        print(f"\nFetching finished in {elapsed_t:,.2f} seconds", flush=True)
    except KeyboardInterrupt:
        print(f"\nUser aborted")
    except Exception as e:
        print(f"\nAn Exception happened: {type(e)}")
    finally:
        print(
            f"\nWaiting for workers to finish backlog ({work_force.backlog_sizes})...",
            end="",
            flush=True,
        )
        work_force.wait_safed()
        print("done.", flush=True)

        print("\nWaiting for workers to disband...", end="", flush=True)
        errors = work_force.disband()
        print("done.")

        print("\nSaving progress so far...", end="", flush=True)
        progress.write_to_path(PROGRESS_FILE)
        print("saved.", flush=True)

    regions_to_build = progress.regions.copy()

    # noinspection PyBroadException
    try:
        build_mosaic(
            regions_to_build,
            progress.seen,
            SAVE_DIR / nightlights_name,
            SAVE_DIR / mosaic_name,
            tot_width=tot_width,
            tot_height=tot_height,
        )
    except KeyboardInterrupt:
        pass
    except Exception:
        raise
    finally:
        elapsed_t = time.monotonic() - start_t
        print(f"ALL DONE. {elapsed_t:,.2f} seconds in total.")
        pp = PrettyPrinter(width=160)
        if errors:
            print("Errors found:")
            pp.pprint(errors)
        else:
            print("  No Errors")
        if progress.last_fail_rows:
            print(f"Last run failed on rows {progress.last_fail_rows}")
            print("  Will be force-read the next run")
        else:
            print("  No failed rows")

    if not errors and not progress.last_fail_rows:
        sys.exit(0)
    else:
        sys.exit(1)


class SplitCommaIntSet(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, set(int(v.strip()) for v in values.split(",")))


def get_options():
    parser = argparse.ArgumentParser()

    parser.add_argument("--xmin", type=int, default=X_MIN_DEFA, help="Minimum X coord")
    parser.add_argument("--xmax", type=int, default=X_MAX_DEFA, help="Maximum X coord")
    parser.add_argument("--ymin", type=int, default=Y_MIN_DEFA, help="Minimum Y coord")
    parser.add_argument("--ymax", type=int, default=Y_MAX_DEFA, help="Maximum Y coord")
    parser.add_argument("--workers", type=int, default=DEFA_WORKERS, help="How many workers to spawn")
    parser.add_argument(
        "--refresh", action="store_true", default=False, help="Forget seen tiles"
    )
    # noinspection PyTypeChecker
    parser.add_argument(
        "--redo",
        action=SplitCommaIntSet,
        dest="redo_rows",
        default=set(),
        help="Rows to redo, comma separated",
    )
    parser.add_argument(
        "--backup",
        type=int,
        metavar="N",
        dest="backup_level",
        default=2,
        help="How many backups to keep",
    )
    parser.add_argument(
        "--nightlights",
        type=str,
        metavar="NAME",
        dest="nightlights_name",
        default=DEFA_NIGHTLIGHTS,
        help="Name of 'nightlights map' file",
    )
    parser.add_argument(
        "--mosaic",
        type=str,
        metavar="NAME",
        dest="mosaic_name",
        default=DEFA_MOSAIC,
        help="Name of world mosaic file",
    )

    opts = parser.parse_args()
    opts.tot_width = TOT_WIDTH
    opts.tot_height = TOT_HEIGHT

    return opts


if __name__ == "__main__":
    print(platform.python_implementation(), platform.python_version())
    options = get_options()
    main(**vars(options))
    # main(X_MIN, X_MAX, Y_MIN, Y_MAX, TOT_WIDTH, TOT_HEIGHT)
