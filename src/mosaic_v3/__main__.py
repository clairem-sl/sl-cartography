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
from pprint import PrettyPrinter
from typing import Iterable, Set, List

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
    x_min,
    x_max,
    y_min,
    y_max,
    redo_rows: Iterable[int] = None,
):
    _redo: Set[int] = set() if redo_rows is None else set(redo_rows)

    make_backup(STATE_FILE_PATH, levels=3)
    progress = MosaicProgress.new_from_path(STATE_FILE_PATH, missing_ok=True)
    _redo.update(progress.failed_rows)
    print(f"These rows will be force-fetched: {sorted(_redo)}")

    global_start = time.monotonic()

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
    recorder_team.start()

    processor_team = WorkTeam(
        num_workers=WORKERS,
        worker_class=TileProcessor,
        output_q=recorder_team.command_queue,
        coordfail_q=coordfail_q,
        err_q=err_q
    )
    processor_team.start()

    # processor = TileProcessorGang(
    #     worker_count=WORKERS,
    #     progress=progress,
    #     progress_file=STATE_FILE_PATH,
    # )
    # processor.start()
    # processor.wait_ready()

    processor_team.wait_ready()
    recorder_team.wait_ready()
    errs: List[str] = []
    try:
        skip_rows = progress.completed_rows - _redo
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
        async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=True) as client:
            row_progress, errs = await async_fetch_area(
                client,
                x_min,
                x_max,
                y_min,
                y_max,
                redo_rows=_redo,
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
        # final_report = processor.disband()
        print()

        progress.failed_rows = row_progress.pending_rows
        progress.failed_rows.update(k for k in progress_proxy.failed_rows.keys())
        progress.write_to_path(STATE_FILE_PATH)

        while not err_q.empty():
            errs.append(err_q.get())
        err_q.close()

    build_mosaic(
        progress.regions,
        progress.completed_rows,
        NIGHTLIGHTS_PATH,
        MOSAIC_PATH,
        tot_width=WORLD_WIDTH,
        tot_height=WORLD_HEIGHT,
    )

    global_elapsed = time.monotonic() - global_start
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
        print("  No failed rows")


if __name__ == "__main__":
    asyncio.run(async_main(0, 2000, 1700, 2000))
