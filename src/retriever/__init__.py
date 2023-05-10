from __future__ import annotations

import asyncio
import signal
import statistics
import sys
import time
from asyncio import Task
from contextlib import contextmanager

from enum import IntEnum

import ruamel.yaml as ryaml

from collections import deque
from pathlib import Path
from typing import TypedDict, Generator, Final, Callable, Any

from sl_maptools import CoordType


class ProgressDict(TypedDict):
    next_x: int
    next_y: int
    outstanding: list[str]


class RetrieverProgress:
    """
    Tracks progress by generating job batches and recording the last issued job.
    """
    DEFA_MIN_COORD: Final[CoordType] = 0, 0
    DEFA_MAX_COORD: Final[CoordType] = 2100, 2100

    def __init__(
        self,
        backing_file: Path,
        auto_reset: bool = True,
        min_coord: CoordType = DEFA_MIN_COORD,
        max_coord: CoordType = DEFA_MAX_COORD,
    ):
        """
        :param backing_file: The YAML file where last state of the object wlll be read-from / written-to
        :param auto_reset: If True (default), will wrap Y coordinate to max upon reaching min
        :param min_coord: Minimum values of X (used in row-wrapping) and Y (used to reset/halt)
        :param max_coord: Maximum values of X (used to wrap to next row) and Y (used to reset)
        """
        self.backing_file = backing_file
        self.auto_reset = auto_reset
        self.minc = min_coord
        self.maxc = max_coord
        self.next_x = min_coord[0]
        self.next_y = max_coord[1]
        self.outstanding: set[tuple[int, int]] = set()
        self._backlog: deque[tuple[int, int]] = deque()
        self.last_dispatch: tuple[int, int] = (-1, -1)
        if backing_file.exists():
            self.load()

    @property
    def next_coordinate(self) -> tuple[int, int]:
        return self.next_x, self.next_y

    @property
    def outstanding_count(self) -> int:
        return len(self.outstanding)

    def retire(self, item: tuple[int, int]):
        if item is None:
            return
        self.outstanding.discard(item)

    def load(self):
        with self.backing_file.open("rt") as fin:
            _last_sess: ProgressDict = ryaml.safe_load(fin)
        if _last_sess is None:
            # noinspection PyTypeChecker
            _last_sess = {}
        self.next_x = _last_sess.get("next_x", self.minc[0])
        self.next_y = _last_sess.get("next_y", self.maxc[1])
        for c in _last_sess.get("outstanding", []):
            x, y = c.split(",")
            self.outstanding.add((int(x), int(y)))
        self._backlog.extend(sorted(self.outstanding, key=lambda t: (t[1], t[0])))

    def save(self):
        exported: ProgressDict = {
            "next_x": self.next_x,
            "next_y": self.next_y,
            "outstanding": [f"{x},{y}" for x, y in sorted(self.outstanding, key=lambda t: (t[1], t[0]))],
        }
        with self.backing_file.open("wt") as fout:
            ryaml.dump(exported, fout, default_flow_style=False)

    async def abatch(self, batch_size: int) -> Generator[tuple[int, int], None, None]:
        c = 0
        while self._backlog:
            c += 1
            yield self._backlog.popleft()
            if c >= batch_size:
                return
        while c < batch_size:
            if self.next_y < self.minc[1]:
                if not self.auto_reset:
                    return
                self.next_y = self.maxc[1]
            job = self.next_x, self.next_y
            if job not in self.outstanding:
                c += 1
                self.outstanding.add(job)
                yield job
                self.last_dispatch = job
            self.next_x += 1
            if self.next_x > self.maxc[0]:
                self.next_x = self.minc[0]
                self.next_y -= 1
                if self.next_y < self.minc[1]:
                    if not self.auto_reset:
                        return
                    self.next_y = self.maxc[1]
                print(f"ROW:{self.next_y}", flush=True)


class DebugLevel(IntEnum):
    DISABLED = 0
    NORMAL = 1
    DETAILED = 2


@contextmanager
def lock_file(lockf: Path, force: bool):
    if not force:
        try:
            lockf.touch(exist_ok=False)
        except FileExistsError:
            print(f"Lock file {lockf} exists!", file=sys.stderr)
            print("You must not run multiple retrievers at the same time.", file=sys.stderr)
            print(
                "If no other retriever is running, delete the lock file to continue.",
                file=sys.stderr,
            )
            sys.exit(1)
    yield
    lockf.unlink(missing_ok=True)


@contextmanager
def handle_sigint(interrupt_flag: asyncio.Event):
    """
    A context manager that provides SIGINT handling, and restore original handler upon exit
    """

    def _handler(_, __):
        if interrupt_flag.is_set():
            return
        interrupt_flag.set()
        print("\n### USER INTERRUPT ###")
        print("Cleaning up in-flight job (if any)...", flush=True)

    orig_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handler)
    yield
    time.sleep(1)
    signal.signal(signal.SIGINT, orig_sigint)


async def dispatch_fetcher(
    progress: RetrieverProgress,
    duration: int,
    taskmaker: Callable[[CoordType], Task],
    result_handler: Callable[[Any], bool],
    pre_batch: Callable,
    post_batch: Callable,
    abort_event: asyncio.Event,
    mavg_samples: int = 5,
    start_batch_size: int = 2000,
    batch_wait: float = 5.0,
):
    start = time.monotonic()
    tasks: set[asyncio.Task] = {taskmaker(coord) async for coord in progress.abatch(start_batch_size)}
    if not tasks:
        print("No undispatched jobs, exiting immediately!")
        return

    total = has_response = 0
    done_last10: deque[int] = deque(maxlen=mavg_samples)
    elapsed_last10: deque[float] = deque(maxlen=mavg_samples)
    done: set[asyncio.Task]
    pending_tasks: set[asyncio.Task]
    while tasks:
        pre_batch()

        # Dispatch
        print(f"{len(tasks)} async jobs =>", end=" ")
        start_batch = time.monotonic()
        done, pending_tasks = await asyncio.wait(tasks, timeout=batch_wait)
        if not abort_event.is_set():
            elapsed_last10.append(time.monotonic() - start_batch)
            done_last10.append(len(done))
        total += len(done)
        batch_size = int(statistics.mean(done_last10)) * 3

        # Handle results
        completed_count = exc_count = 0
        for completed_count, fut in enumerate(done, start=1):
            if exc := fut.exception():
                exc_count += 1
                print(f"\n{fut.get_name()} raised Exception: <{type(exc)}> {exc}")
                continue
            # Actual result handling
            if (fut_result := fut.result()) is not None:
                if result_handler(fut_result):
                    has_response += 1
        if completed_count:
            progress.save()
            if exc_count == completed_count:
                print("\nLast batch all raised Exceptions!")
                print("Cancelling the rest of the tasks...")
                for t in pending_tasks:
                    t.cancel()

        post_batch()

        # Statistics
        elapsed = time.monotonic() - start
        avg_rate = sum(done_last10) / sum(elapsed_last10)
        print(
            f"\n  {elapsed:_.2f}s since start, {total:_} coords scanned "
            f"(mavg. {avg_rate:.2f} r/s), {has_response} regions retrieved"
        )

        # Next iteration
        tasks = pending_tasks
        if elapsed >= duration:
            abort_event.set()
        if abort_event.is_set():
            print("(!A)", end=" ")
            continue
        if (2 * len(tasks)) < batch_size:
            new_tasks = {taskmaker(coord) async for coord in progress.abatch(batch_size)}
            print(f"(+{len(new_tasks)})", end=" ")
            tasks.update(new_tasks)
    if abort_event.is_set():
        print()
