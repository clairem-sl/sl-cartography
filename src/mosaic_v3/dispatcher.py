# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import time
from asyncio import Task
from collections import defaultdict
from typing import Callable, Dict, Generator, Iterable, List, Optional, Set, Tuple

import httpx

from mosaic_v3.workers.tile_processor import ProcessorJob
from sl_maptools import MapCoord
from sl_maptools.fetcher import MapFetcher, RawTile

BATCH_SIZE = 2000
BATCH_WAIT = 2.5
ABORT_WAIT = 5.0
MAX_IN_FLIGHT = 500
DEFA_LOW_WATER = MAX_IN_FLIGHT * 2


class BoundedFetcher:
    """
    Wraps MapFetcher in a way to limit in-flight fetches.

    It does this by implementing a semaphore of a certain size, and only launches an actual fetcher job when it can
    acquire a semaphore.

    This is done to limit the concurrent hit against the SL Maps CDN, because empirical experience seems to indicate
    that if there are too many in-flight requests, we get throttled.
    """

    def __init__(self, sema_size: int, async_session: httpx.AsyncClient, retries: int = 3):
        """

        :param sema_size: Size of semaphore, which limits the number of in-flight requests
        :param async_session: The asynchronous httpx session to be used (connection pool, etc)
        :param retries: How many times to retry if request completes but we get an unexpected HTTP Status Code
        """
        self.sema = asyncio.Semaphore(sema_size)
        self.fetcher = MapFetcher(a_session=async_session)
        self.retries = retries

    async def fetch(self, coord: MapCoord) -> Optional[RawTile]:
        """Perform async fetch, but won't actually start fetching if semaphore is depleted."""
        async with self.sema:
            try:
                return await self.fetcher.async_get_tile_raw(coord, quiet=True, retries=self.retries)
            except asyncio.CancelledError:
                print(f"{coord} cancelled")
                return None


class RowProgress:
    """
    Tracks the progress of job dispatching.
    """

    def __init__(self, row_width: int):
        """
        :param row_width: The overall width of a row, used to determine if a row has completed fetching
        """
        self.row_width = row_width
        self.pending_per_row: Dict[int, int] = {}
        self.regions_per_row: Dict[int, int] = defaultdict(int)
        self.row_starts: Dict[int, float] = {}
        self.fetched_rows: Set[int] = set()

    def inc_region(self, row: int) -> None:
        self.regions_per_row[row] += 1

    def init(self, row: int) -> None:
        if row not in self.pending_per_row:
            self.pending_per_row[row] = self.row_width

    def start(self, row: int) -> None:
        if row not in self.row_starts:
            self.row_starts[row] = time.monotonic()

    def elapsed(self, row: int) -> float:
        if row in self.row_starts:
            return time.monotonic() - self.row_starts[row]

    def dec(self, row: int) -> int:
        if row in self.pending_per_row:
            self.pending_per_row[row] -= 1
            return self.pending_per_row[row]

    def complete(self, row: int) -> None:
        """Mark a row as complete (fully-fetched with no errors during fetch)"""
        if row not in self.pending_per_row and row not in self.row_starts:
            raise KeyError(row)
        del self.pending_per_row[row]
        del self.row_starts[row]
        self.fetched_rows.add(row)

    @property
    def pending_rows(self) -> Set[int]:
        return set(self.pending_per_row.keys())

    def __contains__(self, item: int) -> bool:
        return item in self.fetched_rows or item in self.pending_per_row


async def async_fetch_area(
    client: httpx.AsyncClient,
    x_min: int,
    x_max: int,
    y_min: int,
    y_max: int,
    callback: Callable[[str | ProcessorJob], None] = None,
    redo_rows: Iterable[int] = None,
    skip_rows: Set[int] = None,
    low_water: int = DEFA_LOW_WATER,
    batch_size: int = BATCH_SIZE,
    save_every: int = BATCH_SIZE,
    batch_wait: float = BATCH_WAIT,
) -> Tuple[RowProgress, List[str]]:
    """
    Asynchronously fetch a given area.

    :param client: The asynchronous HTTP client session to use
    :param x_min: Leftmost coordinate
    :param x_max: Rightmost coordinate
    :param y_min: Bottommost coordinate
    :param y_max: Topmost coordinate
    :param callback: A function that will be invoked with each successful fetch. The callback must accept either
    a tuple of (coord, bytes) for successful fetch, or a str "SAVE"
    :param redo_rows: Rows to force redo of fetching. This takes precedence over skip_rows
    :param skip_rows: Rows to skip fetching
    :param low_water: If outstanding jobs are below this level, inject a new batch of jobs
    :param batch_size: How many jobs to inject per injection
    :param save_every: Inject "SAVE" after this many jobs
    :param batch_wait: Time (seconds) to wait for async jobs before determining which ones are completed
    :return: A tuple of final progress result (contains info such as which rows are still pending completion), and
    a list of error messages encountered during fetching.
    """
    skip_rows = skip_rows or set()
    tasks_done_count: int = 0
    pending_tasks: Set[Task] = set()
    row_progress = RowProgress(x_max - x_min + 1)
    rows_done_count: int = 0
    exc_count: int = 0
    redo_rows: Set[int] = set(redo_rows)

    def gen_coords() -> Generator[MapCoord, None, None]:
        """
        Generate coordinates to fetch.

        The logic also considers:
        - Rows to be force-fetched
        - Rows to be skipped

        Note that force-fetch takes precedence over skip. So if a rownum is a member of both the
        force-fetched set and the skipped set, the rownum will be force-fetched.

        :return: A generator that will emit a MapCoord every iteration
        """
        skipping = False
        rowset: Set[int] = set(y for y in range(y_max, y_min - 1, -1)) | redo_rows
        # Reason why we don't just remove the skips from rowset, is so that we can put in a nice
        # "Skipping rows nnn ... nnn" notification there.
        _skips = skip_rows - redo_rows
        for y in sorted(rowset, reverse=True):
            if y in row_progress or y in _skips:
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
                if (coord := next(coords_g, None)) is None:
                    print(f"\n### {i} jobs submitted, no more jobs available", end="", flush=True)
                    coords_g_done = True
                    break
                row_progress.start(coord.y)
                new_task = asyncio.create_task(bfetcher.fetch(coord), name=f"fetch-{coord}")
                pending_tasks.add(new_task)

        try:
            done, pending_tasks = await asyncio.wait(pending_tasks, timeout=batch_wait)
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

            result: Optional[RawTile] = fut.result()
            if result is None:
                continue

            res_y = result[0].y
            if result[1] is not None:
                row_progress.inc_region(res_y)

            if row_progress.dec(res_y) == 0:
                row_elapsed = row_progress.elapsed(res_y)
                row_regs = row_progress.regions_per_row[res_y]
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

            if callback is not None:
                callback(result)
                count += 1
                if count >= save_every:
                    callback("SAVE")
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
        f" {sum(row_progress.regions_per_row.values())} regions fetched.",
        flush=True,
    )
    return row_progress, errs
