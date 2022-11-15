# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import multiprocessing as MP
import time
import warnings
from enum import IntEnum
from multiprocessing import Process
from typing import Protocol, ContextManager, List, Set, Iterable, Any, Tuple


class MPValueProtocol(Protocol):
    value: int

    def get_lock(self) -> ContextManager:
        ...


class WorkerState(IntEnum):
    # Bitwise flags:
    # 0000_0dbr
    #       |++--> 00 = not busy, but not ready
    #       |      01 = not busy, ready
    #       |      10 = busy, not ready
    #       +----> 0 = alive, 1 = dead (or in process of becoming dead)
    SETUP = 0b0000_0000
    READY = 0b0000_0001
    BUSY = 0b0000_0010  # noqa: E221
    DEAD = 0b0000_0100  # noqa: E221
    DYING = 0b0000_0110


class ProcessWithState(Process):
    CommandQueue: MP.Queue = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.CommandQueue is None:
            raise RuntimeError(f"class {self.__class__.name} not initialized properly")
        self.command_queue = self.CommandQueue
        self._state: MPValueProtocol = MP.Value("l", 0)
        self._quiet: MPValueProtocol = MP.Value("l", 1)

    @property
    def state(self):
        return self._state.value

    @state.setter
    def state(self, value: int):
        self._state.value = value

    @property
    def quiet(self):
        return self._quiet.value

    @quiet.setter
    def quiet(self, value: int):
        self._quiet.value = value


class WorkTeam:
    SAFED_STATES: Set[int] = {
        WorkerState.READY,
        WorkerState.DEAD,
    }

    def __init__(
        self, num_workers: int, worker_class: type[ProcessWithState], *args, **kwargs
    ):
        self.num_workers = num_workers
        self.worker_class = worker_class
        self.args = args
        self.kwargs = kwargs
        self.command_queue = MP.Queue()
        self._workers: List[ProcessWithState] = []
        self.__safed = False

    def start(self) -> None:
        self.worker_class.CommandQueue = self.command_queue
        for i in range(0, self.num_workers):
            w = self.worker_class(*self.args, **self.kwargs)
            w.start()
            self._workers.append(w)

    @property
    def ready_count(self) -> int:
        return sum(1 for w in self._workers if w.state == WorkerState.READY)

    @property
    def safed_count(self) -> int:
        return sum(1 for w in self._workers if w.state in self.SAFED_STATES)

    def wait_ready(self) -> None:
        readied = 0
        while readied < self.num_workers:
            time.sleep(1.0)
            readied = self.ready_count

    def wait_safed(
        self, check_queues: List[MP.Queue] = None, quiet: bool = False
    ) -> None:
        qs = [self.command_queue]
        if check_queues is not None:
            qs.extend(check_queues)
        for w in self._workers:
            w.quiet = 1 if quiet else 0
        safed = 0
        while not all(w.empty() for w in qs) or safed < self.num_workers:
            time.sleep(1.0)
            safed = self.safed_count
        self.__safed = True

    def pre_disband(self) -> Any:
        pass

    def post_disband(self) -> Any:
        pass

    def disband(
        self,
        managers: Iterable[MP.managers.SyncManager] = None,
        queues: Iterable[MP.Queue] = None,
    ) -> Tuple[Any, Any]:
        if not self.__safed:
            warnings.warn(
                "disband() before wait_safed() is not recommended!", RuntimeWarning
            )

        pre = self.pre_disband()

        mgrs = []
        if managers is not None:
            mgrs.extend(managers)
        for m in mgrs:
            m.shutdown()
            m.join()

        [self.command_queue.put("DIE") for w in self._workers if w.is_alive()]
        time.sleep(1.0)

        if queues is not None:
            for q in queues:
                q.close()
        self.command_queue.close()

        [w.join() for w in self._workers]

        post = self.post_disband()
        return pre, post

    @property
    def backlog_size(self):
        return self.command_queue.qsize()
