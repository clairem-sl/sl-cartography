# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

# fmt: off
# isort: off
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
import sys
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
from mosaic_v3.workers.recorder import RegionRecorder
from mosaic_v3.workers.processor import ProcessorJob, RegionProcessor
from sl_maptools import MapCoord
from sl_maptools.fetcher import RawRegion
from sl_maptools.utils import make_backup


async def async_main(
    xwest,
    xeast,
    ysouth,
    ynorth,
    statefile: str,
    redo: List[int],
    savedir: Path,
    workers: int,
) -> None:
    """
    Manages/orchestrates the process of Region fetching + mosaic building

    :param xwest: Westernmost "X" Map Coordinate
    :param xeast: Easternmost "X" Map Coordinate
    :param ysouth: Southernmost "Y" Map Coordinate
    :param ynorth: Northernmost "Y" Map Coordinate
    :param statefile: The name of the state file to record progress
    :param redo: List of rows to re-fetch explicitly
    :param savedir: Directory where images will be saved
    :param workers: How many RegionProcessor workers to launch
    :return: None
    """
    print(f"{platform.python_implementation()} {platform.python_version()}")
    print(f"Retrieving Regions within ({xwest},{ynorth})..({xeast},{ysouth}) (inclusive), starting from the top")

    redo_rows: Set[int] = set() if redo is None else set(redo)

    state_file_path = STATE_DIR / statefile
    print(f"Using state file: {state_file_path}")
    make_backup(state_file_path, levels=3)
    progress = MosaicProgress.new_from_path(state_file_path, missing_ok=True)
    old_regs_count = len(progress.regions)
    old_comprows_count = len(progress.completed_rows)
    print(f"Progress so far: {old_regs_count} regions out of {old_comprows_count} complete rows")
    # By adding failed_rows to redo_rows, failed_rows will take precedence (see docstring of async_fetch_area)
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
        worker_class=RegionRecorder,
        progress_proxy=progress_proxy,
        progress_file=state_file_path,
        coordfail_q=coordfail_q,
    )
    recorder_team.start(verbose=True)

    processor_team = WorkTeam(
        num_workers=workers,
        worker_class=RegionProcessor,
        output_q=recorder_team.command_queue,
        coordfail_q=coordfail_q,
        err_q=err_q,
    )
    processor_team.start(verbose=True, start_num=1)
    processor_input_q: MP.Queue[ProcessorJob] = processor_team.command_queue

    processor_team.wait_ready()
    recorder_team.wait_ready()

    def callback(signal: str | RawRegion):
        if isinstance(signal, str):
            if signal.startswith("ROW:"):
                rownum = int(signal.removeprefix("ROW:"))
                progress.completed_rows.add(rownum)
                progress_proxy.completed_rows[rownum] = None
                return
            if signal == "SAVE":
                recorder_team.command_queue.put("SAVE")
                return
        processor_input_q.put(signal)

    # noinspection PyUnusedLocal
    def drain_incoming_q(pteam: WorkTeam, quiet: bool):
        """
        Drains command queue of processor team.

        If there are any jobs left, add the jobs to progress.failed_rows.
        This should NOT ever happen, but we put it here just in case.

        :param pteam: An instance of WorkTeam that handles the RegionProcessors
        :param quiet: Not used
        :return: None
        """
        while not pteam.command_queue.empty():
            job: ProcessorJob = pteam.command_queue.get()
            if not isinstance(job, tuple):
                continue
            co, _ = job
            progress.failed_rows.add(co.y)

    abort = False
    print("\nDispatching jobs:", end="", flush=True)
    try:
        skip_rows = progress.completed_rows - redo_rows
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
        async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=True) as client:
            fetch_progress, errs = await async_fetch_area(
                client,
                xwest,
                xeast,
                ysouth,
                ynorth,
                redo_rows=redo_rows,
                skip_rows=skip_rows,
                callback=callback,
            )
    except KeyboardInterrupt:
        print("User Aborted!", flush=True)
        abort = True
    finally:
        progress.completed_rows.update(fetch_progress.fetched_rows)
        progress_proxy.completed_rows.update({k: None for k in progress.completed_rows})

        backlog = processor_team.backlog_size, recorder_team.backlog_size
        print(f"Waiting for Workers to finish (queued jobs = {backlog})", flush=True)
        processor_team.wait_safed()
        processor_team.disband(quiet=False, pre_disband=drain_incoming_q)
        recorder_team.wait_safed()
        recorder_team.disband(quiet=False, pre_disband=drain_incoming_q)
        print()

        progress.failed_rows |= fetch_progress.pending_rows
        failed_rows = set(k for k in progress_proxy.failed_rows.keys())
        progress.failed_rows.update(failed_rows)
        while not coordfail_q.empty():
            coord, ee = coordfail_q.get()
            progress.failed_rows.add(coord.y)
        coordfail_q.close()

        progress.regions.update(progress_proxy.regions)
        progress.write_to_path(state_file_path)

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

    if abort:
        sys.exit(1)

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
