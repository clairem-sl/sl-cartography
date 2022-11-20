# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import multiprocessing as MP
import time
import warnings
from enum import IntEnum
from multiprocessing import Process
from typing import Any, ContextManager, Iterable, List, Protocol, Set, Tuple


class MPValueProtocol(Protocol):
    """Protocol implemented by multiprocessing.Value"""

    value: int

    def get_lock(self) -> ContextManager:
        ...


class WorkerState(IntEnum):
    """An enumeration of possible states a Worker might be in"""

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


class Worker(Process):
    """
    A subclass of Process with some custom behaviors.

    *) Built-in/enforced CommandQueue
    *) Built-in shared variable for tracking worker state
    *) Built-in shared variable to change worker's 'quietness'

    Please note that Worker.CommandQueue class attribute *must* be set prior to instantating!
    """

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
    def state(self, value: WorkerState):
        self._state.value = value

    @property
    def quiet(self):
        return self._quiet.value

    @quiet.setter
    def quiet(self, value: bool):
        self._quiet.value = value


class WorkTeam:
    """
    Manages a collection of Workers by implementing standard boilerplate operations.

    Workers managed by an instance of this class must be instatiated from Worker a subclass of Worker.
    """

    SAFED_STATES: Set[int] = {
        WorkerState.READY,
        WorkerState.DEAD,
    }

    def __init__(self, num_workers: int, worker_class: type[Worker], *args, **kwargs):
        """
        :param num_workers: Number of workers to instantiate
        :param worker_class: The class to instantiate (must be subclass of Worker)
        :param args: Non-keyword arguments to pass to the workers' class
        :param kwargs: Keyword arguments to pass to the workers' class
        """
        self.num_workers = num_workers
        self.worker_class = worker_class
        self.args = args
        self.kwargs = kwargs
        self.command_queue = MP.Queue()
        self._workers: List[Worker] = []
        self.__safed = False

    def start(self, quiet: bool = True, start_num: int = 0) -> None:
        """
        Instantiates Workers and starts all of them

        :param quiet: If true, suppresses counting of worker started
        :param start_num: Start counting from this number
        :return: None
        """
        self.worker_class.CommandQueue = self.command_queue
        for i in range(0, self.num_workers):
            w = self.worker_class(*self.args, **self.kwargs)
            w.start()
            self._workers.append(w)
            if not quiet:
                print((i + start_num), end=" ", flush=True)

    @property
    def ready_count(self) -> int:
        """Number of workers that have entered the READY state"""
        return sum(1 for w in self._workers if w.state == WorkerState.READY)

    @property
    def safed_count(self) -> int:
        """Number of workers that have entered a 'safe' state (READY or DEAD)"""
        return sum(1 for w in self._workers if w.state in self.SAFED_STATES)

    def wait_ready(self) -> None:
        """
        Waits until all workers are in READY state

        Invoke this before starting to send jobs to the workers.

        :return: None
        """
        readied = 0
        while readied < self.num_workers:
            time.sleep(1.0)
            readied = self.ready_count

    def wait_safed(self, check_queues: List[MP.Queue] = None, quiet: bool = False) -> None:
        """
        Waits until all workers are in a 'safe' state.

        Safe state means workers are either idling (e.g., waiting for a job) or dead,
        and with no incoming job(s) in their input queue(s).

        The objective is to ensure that workers are not in a state where it will change its output queue(s).

        Usually you want to call this right before you send them the poison pill.

        :param check_queues: A list of queues to check that they are empty
        :param quiet: If true, suppresses the workers' output
        :return: None
        """
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
        """Overridable method that will be called before disband() process begins"""
        pass

    def post_disband(self) -> Any:
        """Overridable method that will be called after disband() process completes"""
        pass

    def disband(
        self,
        managers: Iterable[MP.managers.SyncManager] = None,
        queues: Iterable[MP.Queue] = None,
    ) -> Tuple[Any, Any]:
        """
        Performs an orderly shutdown of the Workers.

        :param managers: SyncManager's to shutdown as well, if any.
        They will be shutdown before sending the poison pill to the workers.
        :param queues: multiprocessing queues to close (in addition to the command_queue)
        :return: Reports from pre_disband() and post_disband(), if implemented.
        Subclass the WorkTeam class and override those methods if you need custom pre- and post- behaviors.
        """
        if not self.__safed:
            warnings.warn("disband() before wait_safed() is not recommended!", RuntimeWarning)

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
    def backlog_size(self) -> int:
        """Approximate number of outstanding jobs in the command_queue"""
        return self.command_queue.qsize()
