# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import collections
import math
import re
import signal
import statistics
import sys
import time
from asyncio import Task
from collections import deque
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Final,
    Generator,
    Protocol,
    Type,
    TypedDict,
)

import ruamel.yaml as ryaml

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from sl_maptools import CoordType, MapCoord


class ProgressDict(TypedDict):
    """Tracks progress of retrieval"""

    next_x: int
    next_y: int
    outstanding: list[str]


# fmt: off
class ProgressInterface(Protocol):
    """Protocol for progress tracking"""

    next_coordinate: CoordType
    outstanding_count: int

    def retire(self, item: CoordType) -> None:
        """Retires a job"""
        ...

    def load(self) -> None:
        """Load outstanding jobs from a tracking file"""
        ...

    def save(self) -> None:
        """Save outstanding jobs -- and progress so far -- to a tracking file"""
        ...

    def add(self, coord: CoordType) -> None:
        """Add a job into outstanding set"""
        ...

    def abatch(self, batch_size: int) -> collections.AsyncIterable[CoordType]:
        """
        Asynchronously process a batch of jobs

        :param batch_size: Number of jobs in a batch
        """
        ...


class Dispatchable(Protocol):
    """Protocol for Dispatchable Async Worker"""

    def abatch(self, batch_size: int) -> collections.AsyncIterable[CoordType]:
        """Asynchronously dispatch for a batch"""
        ...

    def save(self) -> None:
        """Save job to a backing file"""
        ...

    def retire(self, item: CoordType) -> None:
        """Retire a job"""
        ...

# fmt: on


class RetrieverProgress:
    """
    Tracks progress by generating job batches and recording the last issued job.

    Attributes
    ----------
        next_coordinate(int): The next coordinate that will be returned by the job generator
        outstanding_count(int): The number of jobs in the outstanding queue
    """

    DEFA_MIN_COORD: Final[CoordType] = 0, 0
    DEFA_MAX_COORD: Final[CoordType] = 2100, 2100

    def __init__(
        self,
        backing_file: Path,
        auto_reset: bool = True,
        min_coord: CoordType = DEFA_MIN_COORD,
        max_coord: CoordType = DEFA_MAX_COORD,
    ) -> None:
        """
        Create a progress tracker.

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
        self.outstanding: set[CoordType] = set()
        self._backlog: deque[CoordType] = deque()
        self.last_dispatch: CoordType = (-1, -1)
        if backing_file.exists():
            self.load()

    @property
    def next_coordinate(self) -> CoordType:
        """Returns the next coordinate that will be returned by the job generator"""
        if self._backlog:
            return self._backlog[0]
        return self.next_x, self.next_y

    @property
    def outstanding_count(self) -> int:
        """How many jobs are still in the outstanding queue (backlog)"""
        return len(self.outstanding)

    def retire(self, item: CoordType | MapCoord) -> None:
        """Remove item from set of outstanding jobs"""
        if item is None:
            return
        self.outstanding.discard(item)

    def load(self) -> None:
        """Load progress from backing file"""
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

    def save(self) -> None:
        """Save progress to backing file"""
        exported: ProgressDict = {
            "next_x": self.next_x,
            "next_y": self.next_y,
            "outstanding": [f"{x},{y}" for x, y in sorted(self.outstanding, key=lambda t: (t[1], t[0]))],
        }
        with self.backing_file.open("wt") as fout:
            ryaml.dump(exported, fout, default_flow_style=False)

    def add(self, coord: CoordType) -> None:
        """Add item into outstanding set"""
        self._backlog.append(coord)
        self.outstanding.add(coord)

    async def abatch(self, batch_size: int) -> Generator[CoordType, None, None]:
        """Generate jobs for a batch"""
        for one in self.batch(batch_size):
            yield one

    def batch(self, batch_size: int) -> Generator[CoordType, None, None]:
        """Generates a batch of coordinates"""
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
    """Debug level"""

    DISABLED = 0
    NORMAL = 1
    DETAILED = 2


@contextmanager
def handle_sigint(interrupt_flag: asyncio.Event) -> None:
    """
    A context manager that provides SIGINT handling, and restore original handler upon exit
    """

    def _handler(_, __) -> None:  # noqa: ANN001
        if interrupt_flag.is_set():
            return
        interrupt_flag.set()
        print("\n### USER INTERRUPT ###")
        print("Cleaning up in-flight job (if any)...", flush=True)

    orig_sigint = signal.signal(signal.SIGINT, _handler)
    yield
    time.sleep(1)
    signal.signal(signal.SIGINT, orig_sigint)


async def dispatch_fetcher(
    progress: Dispatchable,
    duration: int,
    taskmaker: Callable[[CoordType], Task],
    result_handler: Callable[[Any], bool],
    pre_batch: Callable,
    post_batch: Callable,
    abort_event: asyncio.Event,
    mavg_samples: int = 5,
    start_batch_size: int = 2000,
    batch_wait: float = 5.0,
    min_batch_size: int = 0,
    abort_low_rps: int = -1,
) -> None:
    """Asynchronously dispatch jobs"""
    start = time.monotonic()
    tasks: set[asyncio.Task] = {taskmaker(coord) async for coord in progress.abatch(start_batch_size)}
    if not tasks:
        print("No undispatched jobs, exiting immediately!")
        return

    total = has_response = 0
    done_last10: deque[int] = deque(maxlen=mavg_samples)
    elapsed_last10: deque[float] = deque(maxlen=mavg_samples)
    done: set[asyncio.Task]
    while tasks:
        pre_batch()

        # Dispatch
        print(f"{len(tasks)} async jobs =>", end=" ")
        start_batch = time.monotonic()
        
        done, tasks = await asyncio.wait(tasks, timeout=batch_wait)
        
        if not abort_event.is_set():
            elapsed_last10.append(time.monotonic() - start_batch)
            done_last10.append(len(done))
        total += len(done)
        batch_size = max(min_batch_size, int(statistics.mean(done_last10)) * 3)

        # Handle results
        completed_count = exc_count = 0
        for completed_count, task in enumerate(done, start=1):  # noqa: B007
            try:
                exc = task.exception()
            except Exception as e:
                exc = e
            if exc is not None:
                exc_count += 1
                print(f"\n{task.get_name()} raised Exception: <{type(exc)}> {exc}")
                continue

            # Actual result handling
            # result_handler() should perform outstanding jobs retiring!
            if result_handler(task.result()):
                has_response += 1
        progress.save()

        if completed_count and exc_count == completed_count:
            print("\nLast batch all raised Exceptions!")
            print("Cancelling the rest of the tasks...")
            for t in tasks:
                t.cancel()
            done, _ = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
            for t in done:
                try:
                    exc = t.exception()
                except Exception as e:
                    exc = e
                if not isinstance(exc, asyncio.CancelledError):
                    print(f"\n{t.get_name()} raised Exception: <{type(exc)}> {exc}")
            tasks.clear()
            break

        post_batch()

        # Statistics
        elapsed = time.monotonic() - start
        avg_rate = sum(done_last10) / sum(elapsed_last10)
        print(
            f"\n  {elapsed:_.2f}s since start, {total:_} coords scanned "
            f"(mavg. {avg_rate:.2f} r/s), {has_response} regions retrieved"
        )

        # Next iteration
        if statistics.median(done_last10) < abort_low_rps:
            abort_event.set()
        if elapsed >= duration > 0:
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


class RetrieverApplication(AbstractContextManager):
    """
    Defines an application as a ContextManager that performs retrieval
    """

    def __init__(self, *, lock_file: None | Path, log_file: None | Path, force: bool = False) -> None:
        """
        Instantiates this class

        :param lock_file: Lock file to prevent simultaneous run of application
        :param log_file: Log file
        :param force: Force
        """
        self.lock_file = lock_file
        self.log_file = log_file
        self.force = force
        self.started: float
        self.ended: float

    def __enter__(self):
        if self.lock_file is not None:
            lockf = self.lock_file
            try:
                lockf.touch(exist_ok=self.force)
            except FileExistsError as e:
                print(f"Lock file {lockf} exists!", file=sys.stderr)
                print(
                    "You must not run multiple retrievers at the same time.",
                    file=sys.stderr,
                )
                print(
                    "If no other retriever is running, delete the lock file to continue.",
                    file=sys.stderr,
                )
                raise RuntimeError("Lock file exists") from e
        self.started = time.monotonic()
        return self

    def __exit__(
        self,
        __exc_type: Type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> bool | None:
        self.lock_file.unlink(missing_ok=True)
        self.ended = time.monotonic()
        nao = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"\nFinished in {(self.ended - self.started):_.2f} seconds at {nao}")
        return False

    def log(self, log_item: str | dict) -> None:
        """
        Log a dict. If str, marshal that into a dict.
        """
        if self.log_file is None:
            return
        (logf := self.log_file).parent.mkdir(exist_ok=True)
        logf.touch(exist_ok=True)
        with logf.open("rt+") as finout:
            log_data: dict[str, str | dict] = ryaml.safe_load(finout)
            if log_data is None:
                log_data = {}
            if not isinstance(log_item, dict):
                log_item = {"msg": str(log_item)}
            log_data[datetime.now().astimezone().isoformat(timespec="minutes")] = log_item
            finout.seek(0)
            ryaml.dump(log_data, finout)

    class Options(Protocol):
        """Common options for Retriever_v4 modules"""

        force: bool
        min_batch_size: int
        abort_low_rps: int
        duration: int
        until: tuple[int, int]
        until_utc: tuple[int, int]

    class HourMinute(argparse.Action):
        """An Action that tries to parse HH:MM arg"""

        def __call__(self, parser, namespace, values, option_string=None):  # noqa: ANN001, ARG002
            """Will be called by argument parser to parse detected options"""
            m = re.match(r"^(\d{1,2}):(\d{1,2})$", values)
            if m is None or not (0 <= int(m.group(1)) <= 23) or not (0 <= int(m.group(2)) <= 59):  # noqa: PLR2004
                parser.error("Please enter time in 24h HH:MM format!")
            setattr(namespace, self.dest, (int(m.group(1)), int(m.group(2))))

    @staticmethod
    def add_options(parser: argparse.ArgumentParser) -> None:
        """Adds options to the app's ArgumentParser"""
        parser.add_argument("--force", action="store_true", help="Ignore lock file")
        parser.add_argument(
            "--min-batch-size",
            metavar="N",
            type=int,
            default=0,
            help="Batch size will not go lower than this",
        )
        parser.add_argument(
            "--abort-low-rps",
            metavar="N",
            type=int,
            default=-1,
            help="If rps drops below this for some time, abort",
        )

        grp_time = parser.add_mutually_exclusive_group()
        grp_time.add_argument(
            "--duration",
            metavar="SECS",
            type=int,
            default=0,
            help=(
                "Dispatch jobs for SECS seconds. When the duration is reached, stop dispatching new jobs "
                "and try to retire still-in-flight jobs, then exit. If less than 1, that means run forever "
                "until interrupted (Ctrl-C)"
            ),
        )
        grp_time.add_argument(
            "--until",
            metavar="HH:MM",
            action=RetrieverApplication.HourMinute,
            help="Stop dispatching new jobs when wallclock hits this time. WARNING: Does not take DST into account!",
        )
        grp_time.add_argument(
            "--until-utc",
            metavar="HH:MM",
            action=RetrieverApplication.HourMinute,
            help="Same as --until but using UTC time (no DST problem)",
        )

    @staticmethod
    def calc_duration(opts: RetrieverApplication.Options) -> int:
        """Calculate duration (in seconds) given a particular combination of CLI options"""
        nao = datetime.now()
        if opts.duration > 0:
            dur = opts.duration
        elif opts.until:
            hh, mm = opts.until
            unt = nao.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if unt < nao:
                unt = unt + timedelta(days=1)
            dur = (unt - nao).seconds
        elif opts.until_utc:
            hh, mm = opts.until_utc
            nao = nao.astimezone(timezone.utc)
            unt = nao.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if unt < nao:
                unt = unt + timedelta(days=1)
            dur = (unt - nao).seconds
        else:
            dur = math.inf
        return dur
