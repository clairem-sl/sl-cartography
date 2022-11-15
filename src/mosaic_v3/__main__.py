# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

# fmt: off
# isort: off
# import sys
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

import multiprocessing as MP
import time
from pathlib import Path
from pprint import PrettyPrinter
from typing import List, Set

import httpx

from mosaic_v3.builder import build_mosaic
from mosaic_v3.config import *
from mosaic_v3.dispatcher import async_fetch_area
from mosaic_v3.progress import MosaicProgress, MosaicProgressProxy
from mosaic_v3.workers import WorkTeam
from mosaic_v3.workers.recorder import TileRecorder
from mosaic_v3.workers.tile_processor import TileProcessor
from sl_maptools.utils import make_backup


async def async_main(
    xmin,
    xmax,
    ymin,
    ymax,
    redo: List[int],
    savedir: Path,
    workers: int,
):
    print(f"{platform.python_implementation()} {platform.python_version()}")
    print(f"Retrieving tiles within ({xmin},{ymax})..({xmax},{ymin}) (inclusive), starting from the top")

    redo_rows: Set[int] = set() if redo is None else set(redo)

    make_backup(STATE_FILE_PATH, levels=3)
    progress = MosaicProgress.new_from_path(STATE_FILE_PATH, missing_ok=True)
    redo_rows.update(progress.failed_rows)
    print(f"These rows will be force-fetched: {sorted(redo_rows)}")
    progress.failed_rows.clear()

    global_start = time.monotonic()

    print("Launching the workers ... ", end="", flush=True)
    mgr = MP.Manager()
    progress_proxy: MosaicProgressProxy = progress.get_proxies(mgr)
    coordfail_q = MP.Queue()
    err_q = MP.Queue()

    recorder_team = WorkTeam(
        num_workers=1,
        worker_class=TileRecorder,
        progress_proxy=progress_proxy,
        progress_file=STATE_FILE_PATH,
        coordfail_q=coordfail_q,
    )
    recorder_team.start(quiet=False)

    processor_team = WorkTeam(
        num_workers=workers,
        worker_class=TileProcessor,
        output_q=recorder_team.command_queue,
        coordfail_q=coordfail_q,
        err_q=err_q,
    )
    processor_team.start(quiet=False, start_num=1)

    processor_team.wait_ready()
    recorder_team.wait_ready()
    print("\nDispatching jobs:", end="", flush=True)
    try:
        skip_rows = progress.completed_rows - redo_rows
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
        async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=True) as client:
            row_progress, errs = await async_fetch_area(
                client,
                xmin,
                xmax,
                ymin,
                ymax,
                redo_rows=redo_rows,
                skip_rows=skip_rows,
                output_q=processor_team.command_queue,
            )
    except KeyboardInterrupt:
        print("User Aborted!")
    finally:
        progress.completed_rows.update(row_progress.fetched_rows)
        progress_proxy.completed_rows.update({k: None for k in progress.completed_rows})

        backlog = processor_team.backlog_size, recorder_team.backlog_size
        print(f"Waiting for Workers to finish (queued jobs = {backlog})", flush=True)
        processor_team.wait_safed()
        processor_team.disband()
        recorder_team.wait_safed()
        recorder_team.disband()
        print()

        progress.failed_rows = row_progress.pending_rows
        failed_rows = set(k for k in progress_proxy.failed_rows.keys())
        progress.failed_rows.update(failed_rows)
        progress.write_to_path(STATE_FILE_PATH)

        while not err_q.empty():
            errs.append(err_q.get())
        err_q.close()

        mgr.shutdown()
        mgr.join()

    build_mosaic(
        progress.regions,
        progress.completed_rows,
        savedir / NIGHTLIGHTS_NAME,
        savedir / MOSAIC_NAME,
        tot_width=WORLD_WIDTH,
        tot_height=WORLD_HEIGHT,
    )

    global_elapsed = time.monotonic() - global_start
    print("=" * 60)
    print(f"All done in {global_elapsed:,.2f} seconds.")
    if errs:
        print("Errors found:")
        pp = PrettyPrinter(width=160)
        pp.pprint(errs)
    else:
        print("  No Errors")
    if progress.failed_rows:
        print(f"Last run failed on rows {sorted(progress.failed_rows)}")
        print("  Will be force-read the next run")
    else:
        print("  No Failed Rows")


if __name__ == "__main__":
    opts = options()
    asyncio.run(async_main(**vars(opts)))
