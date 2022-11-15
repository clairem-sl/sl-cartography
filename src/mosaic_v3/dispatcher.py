# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import asyncio
import multiprocessing as MP
import time
from asyncio import Task
from collections import defaultdict
from itertools import chain
from typing import Dict, Iterable, List, Optional, Set, Tuple

import httpx

from sl_maptools import MapCoord, MapTile
from sl_maptools.fetcher import MapFetcher

BATCH_SIZE = 2000
BATCH_WAIT = 5.0
ABORT_WAIT = 5.0
MAX_IN_FLIGHT = 500
DEFA_LOW_WATER = MAX_IN_FLIGHT * 2


class BoundedFetcher:
    def __init__(self, sema_size: int, async_session: httpx.AsyncClient):
        self.sema = asyncio.Semaphore(sema_size)
        self.fetcher = MapFetcher(a_session=async_session)

    async def fetch(self, coord: MapCoord) -> Optional[MapTile]:
        async with self.sema:
            try:
                return await self.fetcher.async_get_tile(coord, quiet=True)
            except asyncio.CancelledError:
                print(f"{coord} cancelled")
                return None


class RowProgress:
    def __init__(self, row_width: int, skip_rows: Set[int] = None):
        self.width = row_width
        self.pending: Dict[int, int] = {}
        self.starts: Dict[int, float] = {}
        self.regions: Dict[int, int] = defaultdict(int)
        self.fetched_rows: Set[int] = set()
        if skip_rows:
            self.fetched_rows.update(skip_rows)

    def inc_region(self, row: int):
        self.regions[row] += 1

    def init(self, row: int):
        if row not in self.pending:
            self.pending[row] = self.width

    def start(self, row: int):
        if row not in self.starts:
            self.starts[row] = time.monotonic()

    def elapsed(self, row: int):
        if row in self.starts:
            return time.monotonic() - self.starts[row]

    def dec(self, row: int):
        if row in self.pending:
            self.pending[row] -= 1
            return self.pending[row]

    def complete(self, row: int):
        if row not in self.pending and row not in self.starts:
            raise KeyError(row)
        del self.pending[row]
        del self.starts[row]
        self.fetched_rows.add(row)

    @property
    def pending_rows(self) -> Set[int]:
        return set(self.pending.keys())

    def __contains__(self, item: int):
        return item in self.fetched_rows or item in self.pending


async def async_fetch_area(
    client: httpx.AsyncClient,
    x_min: int,
    x_max: int,
    y_min: int,
    y_max: int,
    output_q: MP.Queue = None,
    redo_rows: Iterable[int] = None,
    skip_rows: Set[int] = None,
    low_water: int = DEFA_LOW_WATER,
    batch_size: int = BATCH_SIZE,
    save_every: int = BATCH_SIZE,
) -> Tuple[RowProgress, List[str]]:
    skip_rows = skip_rows or set()
    tasks_done_count: int = 0
    pending_tasks: Set[Task] = set()
    row_progress = RowProgress(x_max - x_min + 1, skip_rows)
    rows_done_count: int = 0
    exc_count: int = 0

    def gen_coords():
        skipping = False
        for y in chain(redo_rows, range(y_max, y_min - 1, -1)):
            if y in row_progress:
                if not skipping:
                    skipping = True
                    print(f"\nSkipping rows {y}..", end="", flush=True)
                continue
            if skipping:
                skipping = False
                print((y + 1), end="")
            print(f"\nRow {y} begins", end="", flush=True)
            row_progress.init(y)
            for x in range(x_min, x_max + 1):
                _coord = MapCoord(x, y)
                yield _coord
        if skipping:
            print(y_min, end="", flush=True)

    coords_g = gen_coords()
    coords_g_done = False
    done: Set[asyncio.Task] = set()
    abort = False
    bfetcher = BoundedFetcher(MAX_IN_FLIGHT, client)
    global_start = time.monotonic()
    count = 0
    errs = []
    while True:
        if not coords_g_done and len(pending_tasks) < low_water:
            print(f"\n### Adding (up to) {batch_size} jobs!", end="", flush=True)
            for i in range(0, batch_size):
                try:
                    coord = next(coords_g)
                    row_progress.start(coord.y)
                    new_task = asyncio.create_task(bfetcher.fetch(coord), name=f"fetch-{coord}")
                    pending_tasks.add(new_task)
                except StopIteration:
                    print(
                        f"\n### {i} jobs submitted, no more jobs available",
                        end="",
                        flush=True,
                    )
                    coords_g_done = True
                    break

        try:
            done, pending_tasks = await asyncio.wait(pending_tasks, timeout=BATCH_WAIT)
        except ValueError as ve:
            if str(ve) == "Set of Tasks/Futures is empty.":
                break
        except asyncio.CancelledError:
            print(f"\n\nUser aborted!", flush=True)
            abort = True
            break

        tasks_done_count += len(done)
        for fut in done:
            exc = fut.exception()
            if isinstance(exc, Exception):
                errmess = f"{type(exc)}: {exc}"
                print(f"\n!!! {fut.get_name()} Exception {errmess}", flush=True)
                errs.append(errmess)
                exc_count += 1
                continue
            result: MapTile = fut.result()
            if result is None:
                continue
            res_y = result.coord.y
            if not result.is_void:
                row_progress.inc_region(res_y)
            if row_progress.dec(res_y) == 0:
                row_elapsed = row_progress.elapsed(res_y)
                row_regs = row_progress.regions[res_y]
                row_progress.complete(res_y)
                rows_done_count += 1
                global_elapsed = time.monotonic() - global_start
                row_avg_time = global_elapsed / rows_done_count
                print(
                    f"\nRow {res_y} ({row_regs} regions) is done in {row_elapsed:,.2f} seconds,"
                    f" {row_avg_time:,.2f}s avg time per row",
                    end="",
                    flush=True,
                )
            if output_q is not None:
                output_q.put(result)
                count += 1
                if count >= save_every:
                    output_q.put("SAVE")
                    count = 0

        print(
            f"\n"
            f" {tasks_done_count:,} tasks done, {len(pending_tasks)} pending,"
            f" {rows_done_count} rows done, {exc_count} exceptions",
            end="",
            flush=True,
        )
        if coords_g_done and not pending_tasks:
            break
    if abort or pending_tasks:
        for t in pending_tasks:
            t.cancel()
        _, _ = await asyncio.wait(pending_tasks, timeout=ABORT_WAIT)
    global_elapsed = time.monotonic() - global_start
    print(
        f"\n### Fetching is complete, {global_elapsed:,.2f} seconds."
        f" {sum(row_progress.regions.values())} regions fetched.",
        flush=True,
    )
    return row_progress, errs
