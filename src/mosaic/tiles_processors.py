# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import time
import multiprocessing as MP
from multiprocessing import Process
from typing import (
    Dict,
    Any,
    Tuple,
    List,
    Callable,
    Generator,
    Protocol,
    ContextManager,
    Set,
)
from pathlib import Path

from mosaic.color_processing import DominantColors
from sl_maptools import MapCoord, MapTile
from mosaic.progress import MosaicProgress


class MPValueProtocol(Protocol):
    value: int

    def get_lock(self) -> ContextManager:
        ...


class TileProcessorWorker(Process):
    STATE_SETUP = 1
    STATE_READY = 2
    STATE_BUSY = 3
    STATE_DEAD = -1

    def __init__(
        self,
        tile_queue: MP.Queue,
        regions_dict: Dict[MapCoord, DominantColors],
        seen_dict: Dict[MapCoord, None],
        proglock: MP.Lock,
        errqueue: MP.Queue,
        failqueue: MP.Queue,
        progress_file: Path,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.tile_queue = tile_queue
        self.regions_dict = regions_dict
        self.seen_dict = seen_dict
        self.proglock = proglock
        self.errqueue = errqueue
        self.failqueue = failqueue
        self.progress_file = progress_file

        self._state: MPValueProtocol = MP.Value("l", 0)

    @property
    def state(self) -> int:
        return self._state.value

    def run(self):
        self._state.value = self.STATE_SETUP
        count = 0
        tile = None
        try:
            while True:
                self._state.value = self.STATE_READY
                tile = self.tile_queue.get()

                if tile == "DIE":
                    print("X", end="", flush=True)
                    break

                self._state.value = self.STATE_BUSY

                if tile == "ROW" or tile == "SAVE":
                    print("~", end="", flush=True)
                    for _ in range(0, 3):
                        try:
                            wprogress = MosaicProgress(
                                regions=dict(self.regions_dict),
                                seen=set(self.seen_dict.keys()),
                            )
                            with self.proglock:
                                wprogress.write_to_path(self.progress_file)
                            break
                        except (PermissionError, IOError):
                            time.sleep(1.0)
                    continue

                assert isinstance(tile, MapTile)
                try:
                    if not tile.is_void:
                        self.regions_dict[tile.coord] = DominantColors.from_tile(tile)
                    elif tile.coord in self.regions_dict:
                        del self.regions_dict[tile.coord]
                    self.seen_dict[tile.coord] = None
                except Exception as ew:
                    errmess = f"ERR[{type(ew)}:{ew}]({tile.coord.x},{tile.coord.y})"
                    print(errmess, end="", flush=True)
                    self.errqueue.put(errmess)
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
                self._state.value = self.STATE_DEAD
                self.tile_queue.close()
                self.errqueue.close()
                self.failqueue.close()
                time.sleep(1.0)
            except Exception:
                pass


class TileProcessorGang:
    SAFED_STATES: Set[int] = {
        TileProcessorWorker.STATE_READY,
        TileProcessorWorker.STATE_DEAD,
    }

    def __init__(self, count: int, progress: MosaicProgress, progress_file: Path):
        self.count = count
        self.progress_file = progress_file

        self.mgr = MP.Manager()
        mgr = self.mgr
        self.mpm_regions, self.mpm_seen = progress.get_managed(mgr)
        self.mpm_proglock = mgr.Lock()
        self.mpm_errsqueue = mgr.Queue()
        self.mpm_failqueue = mgr.Queue()

        # Don't use mgr.Queue because this must survive after mgr dies
        self.mp_jobqueue = MP.Queue()

        self.workers: List[TileProcessorWorker] = []

    def prime(self):
        for i in range(0, self.count):
            print(i, end=" ", flush=True)
            w = TileProcessorWorker(
                self.mp_jobqueue,
                self.mpm_regions,
                self.mpm_seen,
                self.mpm_proglock,
                self.mpm_errsqueue,
                self.mpm_failqueue,
                self.progress_file,
            )
            w.start()
            self.workers.append(w)

    @property
    def ready_count(self):
        return sum(
            1 for w in self.workers if w.state == TileProcessorWorker.STATE_READY
        )

    @property
    def safed_count(self):
        return sum(1 for w in self.workers if w.state in self.SAFED_STATES)

    def wait_ready(self):
        readied_workers = 0
        while readied_workers < self.count:
            time.sleep(1.0)
            readied_workers = self.ready_count

    def wait_safed(self):
        safed_workers = 0
        while safed_workers < self.count:
            time.sleep(1.0)
            safed_workers = self.safed_count

    def disband(self):
        # Shutting down the manager before ending the workers prevents GetOverlappedResult err/warning
        # After all at this point in time we no longer need the facilities of SyncManager
        self.mgr.shutdown()
        self.mgr.join()

        # At this point all workers are lame ducks and cannot do anything but to disband.
        # So, we tell workers to disband
        [self.mp_jobqueue.put("DIE") for w in self.workers if w.is_alive()]
        time.sleep(1.0)
        self.mp_jobqueue.close()
        [w.join() for w in self.workers]

    @staticmethod
    def drain_queue(queue: MP.Queue, fun: Callable[[Any], Any] = None):
        while not queue.empty():
            item = queue.get()
            if fun:
                yield fun(item)
            else:
                yield item

    def drain_errsqueue(self) -> Generator[str, None, None]:
        yield from self.drain_queue(self.mpm_errsqueue)

    def drain_failqueue(self) -> Generator[Tuple[MapCoord, Exception], None, None]:
        yield from self.drain_queue(self.mpm_failqueue)

    @property
    def backlog_size(self) -> int:
        return self.mp_jobqueue.qsize()
