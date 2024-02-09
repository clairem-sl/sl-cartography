# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import contextlib
import multiprocessing as MP
import multiprocessing.managers as MPMgr
import multiprocessing.pool as mp_pool
import pickle
import queue
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Optional, Protocol, TypedDict, cast

from ruamel.yaml import YAML, RoundTripRepresenter

# noinspection PyProtectedMember
from retriever_v4.maps._workers.retriever import retrieve

# noinspection PyProtectedMember
from retriever_v4.maps._workers.saver import saver
from retriever_v4.maps.prune import prune
from sl_maptools import CoordType, SupportsSet, inventorize_maps_all
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.utils import handle_sigint, make_backup

if TYPE_CHECKING:
    from retriever_v4.maps import QResult

INFO_EVERY: Final[float] = 5.0

RETR_WORKERS: Final[int] = max((MP.cpu_count() - 2) * 2, 2)
SAVE_WORKERS: Final[int] = min((RETR_WORKERS // 2), 4)

START_ROW: Final[int] = 2100

AbortRequested: SupportsSet = MP.Event()


class MPMapOptions(Protocol):
    """Represents the options parsed from CLI"""

    workers: int
    savers: int
    prune_on_abort: bool
    prune: bool


def get_options() -> MPMapOptions:
    """Get options from CLI"""
    parser = argparse.ArgumentParser("retriever.maps.mp")

    parser.add_argument("--workers", type=int, default=RETR_WORKERS)
    parser.add_argument("--savers", type=int, default=SAVE_WORKERS)

    grp_prune = parser.add_mutually_exclusive_group()
    grp_prune.add_argument(
        "--prune-on-abort",
        action="store_true",
        help="Prune on abort as well",
    )
    grp_prune.add_argument("--prune", action="store_true", default=False, help="Prune after finish")

    _opts = parser.parse_args()
    return cast(MPMapOptions, _opts)


class ProgressDict(TypedDict):
    """Represents the progress of map retrieval"""

    next_row: Optional[int]
    backlog: set[CoordType]


class ProgressionDict(TypedDict):
    """Represents per-row progression of map retrieval"""

    start: Optional[datetime]
    done: int
    last: Optional[datetime]


def launch_workers(
    opts: MPMapOptions, progress: ProgressDict, mgr: MPMgr.SyncManager
) -> tuple[int, set[CoordType], dict[int, ProgressionDict], list[QResult]]:
    """Launches MP workers"""
    errs: list[QResult] = []
    coord_queue: MP.Queue = mgr.Queue()
    save_queue: MP.Queue = mgr.Queue(maxsize=4000)
    dispatched_queue: MP.Queue = mgr.Queue()
    result_queue: MP.Queue = mgr.Queue()

    r_args = (
        coord_queue,
        save_queue,
        dispatched_queue,
        result_queue,
        AbortRequested,
    )
    s_args = (Path(Config.maps.dir), save_queue, result_queue)

    progression: dict[int, ProgressionDict] = {y: {"start": None, "done": 0, "last": None} for y in range(0, 2101)}
    outstanding: set[CoordType] = set()
    total: int = 0
    count: int = 0

    def flush_dispatched_queue(msg: bool = False) -> None:
        nonlocal count
        try:
            if msg:
                print("Flushing dispatch queue", flush=True)
            while True:
                di = dispatched_queue.get_nowait()
                if isinstance(di, list):
                    outstanding.update(cast(list[CoordType], di))
                elif isinstance(di, int):
                    count += di
        except queue.Empty:
            pass

    def flush_result_queue(msg: bool = False) -> None:
        nonlocal total
        try:
            if msg:
                print("Flushing result queue", flush=True)
            while True:
                rslt: QResult = result_queue.get_nowait()
                if rslt.exc is None:
                    outstanding.discard(cast(CoordType, rslt.coord))
                    if rslt.entity.startswith("Saver"):
                        total += 1
                    else:
                        _, y = rslt.coord
                        _prog = progression[y]
                        if _prog["start"] is None:
                            _prog["start"] = datetime.now()
                        _prog["done"] += 1
                        _prog["last"] = datetime.now()
                else:
                    errs.append(rslt)
        except queue.Empty:
            pass

    def dispatch_backlog() -> None:
        backlog = sorted(progress["backlog"], key=lambda i: (i[1], i[0]))
        if backlog:
            _chunksize = (len(backlog) // opts.workers) + 1
            _chunksize = min(2000, _chunksize)
            _i = 0
            while _i < len(backlog):
                coord_queue.put(("set", backlog[_i : (_i + _chunksize)]))
                _i += _chunksize

    pool_r: mp_pool.Pool
    pool_s: mp_pool.Pool
    try:
        with (
            handle_sigint(AbortRequested),
            MP.Pool(opts.workers, initializer=retrieve, initargs=r_args) as pool_r,
            MP.Pool(opts.savers, initializer=saver, initargs=s_args) as pool_s,
            contextlib.ExitStack() as stack,
        ):
            # These will be called in reverse order!
            stack.callback(flush_result_queue, True)
            stack.callback(flush_dispatched_queue, True)
            #
            dispatch_backlog()

            for row in range(progress["next_row"], -1, -1):
                coord_queue.put(("row", row))

            tm: float = time.monotonic()
            while not coord_queue.empty():
                flush_dispatched_queue()
                flush_result_queue()
                elapsed = time.monotonic() - tm
                if elapsed >= INFO_EVERY:
                    rate = count / elapsed
                    print(
                        f"{count:_} coords checked, at {rate:_.2f}rps, {total:_} retrieved",
                        flush=True,
                    )
                    count = 0
                    tm = time.monotonic()
                if AbortRequested.is_set():
                    print("\n### ABORT REQUESTED! ###\n")
                    pool_r.close()
                    break
            else:
                print("Telling retriever workers to end")
                pool_r.close()
                for _ in range(opts.workers):
                    coord_queue.put(None)
            print("Joining retriever workers")
            pool_r.join()

            print("Flushing coord_queue")
            next_row = None
            try:
                cmd, det = coord_queue.get_nowait()
                if cmd == "row":
                    if next_row is None:
                        next_row = det
                elif cmd == "single":
                    outstanding.add(det)
                elif cmd == "set":
                    outstanding.update(det)
            except queue.Empty:
                pass

            print("Telling saver workers to end")
            pool_s.close()
            for _ in range(opts.savers):
                save_queue.put(None)
            print("Joining saver workers")
            pool_s.join()

    finally:
        return next_row, outstanding, progression, errs  # noqa: B012


def main(opts: MPMapOptions) -> None:  # noqa: D103
    start = time.monotonic()

    mapdir = Path(Config.maps.dir)
    progress_file = mapdir / Config.maps.progress
    if progress_file.exists():
        with progress_file.open("rb") as fin:
            progress: ProgressDict = pickle.load(fin)  # noqa: S301
        if progress["next_row"] is None:
            progress["next_row"] = -1
    else:
        progress = {
            "next_row": START_ROW,
            "backlog": set(),
        }
    print(f"Backlog from previous run: {len(progress['backlog']):_}\nNext row after backlog: {progress['next_row']}")

    errs: list[QResult]
    mgr: MPMgr.SyncManager
    try:
        with MP.Manager() as mgr:
            next_row, outstanding, progression, errs = launch_workers(opts, progress, mgr)
    finally:
        progress = {
            "next_row": next_row,
            "backlog": outstanding,
        }
        with progress_file.open("wb") as fout:
            pickle.dump(progress, fout)

    if errs:
        print("During retrieval, the following errors are seen:", file=sys.stderr)
        time.sleep(1)
        for entity, _coord, exc in errs:
            print(f"    {entity} <{type(exc)}>{exc}", file=sys.stderr)
        time.sleep(1)
        print(f"  A total of {len(errs)} errors", file=sys.stderr)

    normalized_time_per_row: dict[int, float] = {}
    for y, prog in progression.items():
        n = prog["done"]
        if n == 0:
            continue
        if prog["start"] is None or prog["last"] is None:
            continue
        delta = prog["last"] - prog["start"]
        if delta.seconds < 0.1:  # noqa: PLR2004
            continue
        normalized_time_per_row[y] = 2100 * delta.seconds / n
    yaml = YAML(typ="safe")
    yaml.Representer = RoundTripRepresenter
    perfdata: dict[datetime, dict[int, float]] = {}
    performance_file = mapdir / "performance.yaml"
    if performance_file.exists():
        make_backup(performance_file)
        with performance_file.open("rt") as fin:
            perfdata = yaml.load(fin)
    perfdata[datetime.now().astimezone()] = normalized_time_per_row
    with performance_file.open("wt") as fout:
        yaml.dump(perfdata, fout)

    print(f"{len(outstanding):_} coordinates in backlog, next row will be {next_row}")

    finish = time.monotonic()
    print(f"Finished in {finish - start:_.2f}s on {datetime.now().isoformat(timespec='minutes')}")

    if not opts.prune:
        return

    if AbortRequested.is_set() and not opts.prune_on_abort:
        return

    print("Starting prune:", flush=True)
    total, count = prune(inventorize_maps_all(mapdir), quiet=True)
    print(f"{total - count} files pruned.")


if __name__ == "__main__":
    options = get_options()
    main(options)
