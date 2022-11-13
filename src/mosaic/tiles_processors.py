# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import multiprocessing as MP
import time
from enum import IntEnum
from multiprocessing import Process
from pathlib import Path
from typing import (
    Any,
    Callable,
    ContextManager,
    Dict,
    Generator,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
)

from mosaic.color_processing import DominantColors
from mosaic.progress import MosaicProgress
from sl_maptools import MapCoord, MapTile


class MPValueProtocol(Protocol):
    value: int

    def get_lock(self) -> ContextManager:
        ...


# Bitwise flags:
# 0000_0dbr
#       |++--> 00 = not busy, but not ready
#       |      01 = not busy, ready
#       |      10 = busy, not ready
#       +----> 0 = alive, 1 = dead (or in process of becoming dead)

class WorkerState(IntEnum):
    SETUP = 0b0000_0000
    READY = 0b0000_0001
    BUSY  = 0b0000_0010  # noqa: E221
    DEAD  = 0b0000_0100  # noqa: E221
    DYING = 0b0000_0110


class ProcessWithState(Process):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state: MPValueProtocol = MP.Value("l", 0)

    @property
    def state(self):
        return self._state.value

    @state.setter
    def state(self, value: int):
        self._state.value = value


class TileProcessorWorker(ProcessWithState):
    def __init__(
        self,
        tile_queue: MP.Queue,
        outgoing_queue: MP.Queue,
        errmessq: MP.Queue,
        failqueue: MP.Queue,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.tile_queue = tile_queue
        self.outgoing_queue = outgoing_queue
        self.errmessq = errmessq
        self.failqueue = failqueue

    def run(self):
        self.state = WorkerState.SETUP
        count = 0
        tile = None
        try:
            while True:
                self.state = WorkerState.READY
                tile = self.tile_queue.get()

                if tile == "DIE":
                    self.state = WorkerState.DYING
                    print("X", end="", flush=True)
                    break

                self.state = WorkerState.BUSY

                if tile == "ROW" or tile == "SAVE":
                    self.outgoing_queue.put("SAVE")
                    print("~", end="", flush=True)
                    continue

                assert isinstance(tile, MapTile)
                try:
                    if not tile.is_void:
                        domc = DominantColors.from_tile(tile)
                    else:
                        domc = None
                    self.outgoing_queue.put((tile.coord, domc))
                except Exception as ew:
                    errmess = f"ERR[{type(ew)}:{ew}]({tile.coord.x},{tile.coord.y})"
                    print(errmess, end="", flush=True)
                    self.errmessq.put(errmess)
                    self.failqueue.put_nowait((tile.coord, ew))

                count += 1
                if count >= 100:
                    print("*", end="", flush=True)
                    count = 0
        except (KeyboardInterrupt, Exception) as ee:
            if isinstance(tile, MapTile):
                self.failqueue.put((tile.coord, ee))
            if not isinstance(ee, KeyboardInterrupt):
                raise
        finally:
            # noinspection PyBroadException
            try:
                self.state = WorkerState.DEAD
                self.tile_queue.close()
                self.outgoing_queue.close()
                self.errmessq.close()
                self.failqueue.close()
                time.sleep(1.0)
            except Exception:
                pass


class TileProcessorRecorder(ProcessWithState):
    MIN_SAVE_DISTANCE = 200

    def __init__(
        self,
        incoming: MP.Queue,
        progresss_so_far: MosaicProgress,
        progress_file: Path,
        flushqueue: MP.Queue,
        failqueue: MP.Queue,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.incoming = incoming
        self.regions_dict = progresss_so_far.regions
        self.seen_dict = progresss_so_far.seen
        self.prev_failrows = progresss_so_far.last_fail_rows
        self.progress_file = progress_file
        self.flushqueue = flushqueue
        self.failqueue = failqueue

    def _save(self, regions: Dict[MapCoord, DominantColors], seen: Set[MapCoord]):
        MosaicProgress(
            regions=regions,
            seen=seen,
            last_fail_rows=self.prev_failrows
        ).write_to_path(self.progress_file)

    def run(self) -> None:
        self.state = WorkerState.SETUP
        regions = dict(self.regions_dict)
        seen_set: Set[MapCoord] = set(self.seen_dict)
        tile: Optional[MapTile] = None
        count_between_saves = 0
        try:
            while True:
                self.state = WorkerState.READY
                job = self.incoming.get()

                if job == "DIE":
                    self.state = WorkerState.DYING
                    self._save(regions, seen_set)
                    print("Z", end="", flush=True)
                    break

                self.state = WorkerState.BUSY

                if job == "SAVE":
                    if (
                        count_between_saves < self.MIN_SAVE_DISTANCE
                        and not self.incoming.empty()
                    ):
                        continue
                    count_between_saves = 0
                    print("V", end="", flush=True)
                    self._save(regions, seen_set)
                    continue

                if job == "FLUSH":
                    self.flushqueue.put(regions)
                    self.flushqueue.put(seen_set)
                    continue

                assert isinstance(job, tuple)
                assert len(job) == 2
                count_between_saves += 1
                coord: MapCoord = job[0]
                domc: Optional[DominantColors] = job[1]

                seen_set.add(coord)
                if domc is None:
                    if coord in regions:
                        del regions[coord]
                    continue
                else:
                    regions[coord] = domc
        except (KeyboardInterrupt, Exception) as ee:
            if isinstance(tile, MapTile):
                self.failqueue.put((tile.coord, ee))
            if not isinstance(ee, KeyboardInterrupt):
                raise
        finally:
            # noinspection PyBroadException
            try:
                self.state = WorkerState.DEAD
                self.incoming.close()
                self.failqueue.close()
                time.sleep(1.0)
            except Exception:
                pass


class TileProcessorGang:
    SAFED_STATES: Set[int] = {
        WorkerState.READY,
        WorkerState.DEAD,
    }

    def __init__(self, count: int, progress: MosaicProgress, progress_file: Path):
        self.count = count
        self.progress = progress
        self.progress_file = progress_file

        self.mgr = MP.Manager()
        mgr = self.mgr
        # self.mpm_regions = mgr.dict(progress.regions)
        # self.mpm_seen = mgr.dict({k: None for k in progress.seen})
        self.mpm_errmessq = mgr.Queue()
        self.mpm_flushqueue = mgr.Queue()
        self.mpm_failqueue = mgr.Queue()

        # Don't use mgr.Queue because these must survive after mgr dies
        self.mp_tilequeue = MP.Queue()
        self.mp_tiledomcq = MP.Queue()

        self.workers: List[TileProcessorWorker] = []
        self.recorder: Optional[TileProcessorRecorder] = None

    def prime(self):
        for i in range(0, self.count):
            print(i, end=" ", flush=True)
            w = TileProcessorWorker(
                self.mp_tilequeue,
                self.mp_tiledomcq,
                self.mpm_errmessq,
                self.mpm_failqueue,
            )
            w.start()
            self.workers.append(w)
        self.recorder = TileProcessorRecorder(
            self.mp_tiledomcq,
            self.progress,
            self.progress_file,
            self.mpm_flushqueue,
            self.mpm_failqueue,
        )
        self.recorder.start()

    @property
    def ready_count(self):
        return sum(1 for w in self.workers if w.state == WorkerState.READY)

    @property
    def safed_count(self):
        return sum(1 for w in self.workers if w.state in self.SAFED_STATES)

    def wait_ready(self):
        readied_workers = 0
        while readied_workers < self.count:
            time.sleep(1.0)
            readied_workers = self.ready_count
        while self.recorder.state != WorkerState.READY:
            time.sleep(1.0)

    def wait_safed(self):
        safed_workers = 0
        while not self.mp_tilequeue.empty() or safed_workers < self.count:
            time.sleep(1.0)
            safed_workers = self.safed_count
        self.mp_tiledomcq.put("SAVE")
        while not self.mp_tiledomcq.empty() or (
            self.recorder.state not in self.SAFED_STATES
        ):
            time.sleep(1.0)

    def disband(self) -> List[str]:
        self.mp_tiledomcq.put("FLUSH")
        time.sleep(1.0)
        while self.recorder.state != WorkerState.READY:
            time.sleep(1.0)
        self.progress.regions.update(self.mpm_flushqueue.get())
        self.progress.seen.update(self.mpm_flushqueue.get())
        self.progress.last_fail_rows.update(coord.y for coord, ex in self.drain_failqueue())
        errs = [err for err in self.drain_errsqueue()]

        # Shutting down the manager before ending the workers prevents GetOverlappedResult err/warning
        # After all at this point in time we no longer need the facilities of SyncManager
        self.mgr.shutdown()
        self.mgr.join()

        # At this point all workers are lame ducks and cannot do anything but to disband.
        # So, we tell workers to disband
        [self.mp_tilequeue.put("DIE") for w in self.workers if w.is_alive()]
        self.mp_tiledomcq.put("DIE")
        time.sleep(1.0)
        self.mp_tilequeue.close()
        self.mp_tiledomcq.close()
        [w.join() for w in self.workers]
        self.recorder.join()

        return errs

    @staticmethod
    def drain_queue(queue: MP.Queue, fun: Callable[[Any], Any] = None):
        while not queue.empty():
            item = queue.get()
            if fun:
                yield fun(item)
            else:
                yield item

    def drain_errsqueue(self) -> Generator[str, None, None]:
        yield from self.drain_queue(self.mpm_errmessq)

    def drain_failqueue(self) -> Generator[Tuple[MapCoord, Exception], None, None]:
        yield from self.drain_queue(self.mpm_failqueue)

    @property
    def backlog_sizes(self) -> Tuple[int, int]:
        return self.mp_tilequeue.qsize(), self.mp_tiledomcq.qsize()
