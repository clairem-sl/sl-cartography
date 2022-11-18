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

import datetime
import multiprocessing as MP
import time
from pathlib import Path
from pprint import PrettyPrinter
from typing import List, Set, Tuple

import httpx

from mosaic_v3.builder import build_world_maps
from mosaic_v3.config import *
from mosaic_v3.dispatcher import async_fetch_area
from mosaic_v3.progress import MosaicProgress, MosaicProgressProxy
from mosaic_v3.workers import WorkTeam
from mosaic_v3.workers.recorder import TileRecorder
from mosaic_v3.workers.tile_processor import ProcessorJob, TileProcessor
from sl_maptools import MapCoord
from sl_maptools.utils import make_backup


async def async_main(
    xmin,
    xmax,
    ymin,
    ymax,
    redo: List[int],
    savedir: Path,
    workers: int,
) -> None:
    """
    Manages/orchestrates the process of map tile fetching + mosaic building

    :param xmin: Leftmost tile
    :param xmax: Rightmost tile
    :param ymin: Bottommost tile
    :param ymax: Topmost tile
    :param redo: List of rows to re-fetch explicitly
    :param savedir: Directory where images will be saved
    :param workers: How many TileProcessor workers to launch
    :return: None
    """
    print(f"{platform.python_implementation()} {platform.python_version()}")
    print(f"Retrieving tiles within ({xmin},{ymax})..({xmax},{ymin}) (inclusive), starting from the top")

    redo_rows: Set[int] = set() if redo is None else set(redo)

    make_backup(STATE_FILE_PATH, levels=3)
    progress = MosaicProgress.new_from_path(STATE_FILE_PATH, missing_ok=True)
    old_regs_count = len(progress.regions)
    old_comprows_count = len(progress.completed_rows)
    print(f"Progress so far: {old_regs_count} regions out of {old_comprows_count} complete rows")
    redo_rows.update(progress.failed_rows)
    print(f"These rows will be force-fetched: {sorted(redo_rows)}")
    progress.failed_rows.clear()

    global_start = time.monotonic()

    print("Launching the workers ... ", end="", flush=True)
    mgr = MP.Manager()
    progress_proxy: MosaicProgressProxy = progress.get_proxies(mgr)
    coordfail_q: MP.Queue[Tuple[MapCoord, Exception]] = MP.Queue()
    err_q: MP.Queue[str] = MP.Queue()

    recorder_team = WorkTeam(
        num_workers=1,
        worker_class=TileRecorder,
        progress_proxy=progress_proxy,
        progress_file=STATE_FILE_PATH,
        coordfail_q=coordfail_q,
    )
    recorder_team.start(verbose=False)

    processor_team = WorkTeam(
        num_workers=workers,
        worker_class=TileProcessor,
        output_q=recorder_team.command_queue,
        coordfail_q=coordfail_q,
        err_q=err_q,
    )
    processor_team.start(verbose=False, start_num=1)
    processor_input_q: MP.Queue[ProcessorJob] = processor_team.command_queue

    processor_team.wait_ready()
    recorder_team.wait_ready()

    def callback(signal: ProcessorJob):
        if isinstance(signal, str) and signal.startswith("ROW:"):
            rownum = int(signal.removeprefix("ROW:"))
            progress.completed_rows.add(rownum)
            progress_proxy.completed_rows[rownum] = None
            return
        processor_input_q.put(signal)

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
                callback=callback,
            )
    except KeyboardInterrupt:
        print("User Aborted!")
    finally:
        progress.completed_rows.update(row_progress.fetched_rows)
        progress_proxy.completed_rows.update({k: None for k in progress.completed_rows})

        backlog = processor_team.backlog_size, recorder_team.backlog_size
        print(f"Waiting for Workers to finish (queued jobs = {backlog})", flush=True)
        processor_team.wait_safed()
        processor_team.disband(quiet=False)
        recorder_team.wait_safed()
        recorder_team.disband(quiet=False)
        print()

        progress.failed_rows = row_progress.pending_rows
        failed_rows = set(k for k in progress_proxy.failed_rows.keys())
        progress.failed_rows.update(failed_rows)
        while not coordfail_q.empty():
            coord, ee = coordfail_q.get()
            progress.failed_rows.add(coord.y)
        coordfail_q.close()

        progress.regions.update(progress_proxy.regions)
        progress.write_to_path(STATE_FILE_PATH)

        while not err_q.empty():
            errs.append(err_q.get())
        err_q.close()

        mgr.shutdown()
        mgr.join()

    print(
        f"Fetch phase adds {len(progress.regions) - old_regs_count} new regions,"
        f" {len(progress.completed_rows) - old_comprows_count} new rows.",
        flush=True,
    )

    build_world_maps(
        progress.regions,
        progress.completed_rows,
        savedir / NIGHTLIGHTS_NAME,
        savedir / MOSAIC_NAME,
        corner1=MapCoord(0, 0),
        corner2=MapCoord(2000, 2000),
    )

    global_elapsed = time.monotonic() - global_start
    nao = datetime.datetime.now()
    print("=" * 60)
    print(f"All done in {global_elapsed:,.2f} seconds at {nao.strftime('%H:%M')}")
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
