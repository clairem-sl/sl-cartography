# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import copy
import multiprocessing as MP
import time
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple, Union

from mosaic_v3.color_processing import DominantColors
from mosaic_v3.progress import MosaicProgressProxy
from mosaic_v3.workers import Worker, WorkerState
from sl_maptools import MapCoord

RecorderSignals = Union[Literal["DIE"], Literal["FLUSH"], Literal["SAVE"]]
RecorderJob = Union[RecorderSignals, Tuple[MapCoord, DominantColors]]


class RegionRecorder(Worker):
    """
    Receives Regions that have been processed, and record them.

    This will record not just into a proxied Progress object, but also (optionally) to disk.

    IN ADDITION, this worker will also gather the failed Regions and record them also into the proxied Progress object.

    This class recognizes the following 'jobs' in the input/command queue:
    - "DIE" instruction to wrap up and end
    - "FLUSH" will sync the in-memory data with the SyncManager-managed MapProgressProxy object
    - "SAVE" instruction to save progress so far; will also trigger flush
    - (MapCoord, DominantColors) -- actual data to be accumulated (not yet written to disk until "SAVE" is received)
    """

    MIN_SAVE_DISTANCE = 200

    def __init__(
        self,
        *args,
        progress_proxy: MosaicProgressProxy,
        progress_file: Path,
        coordfail_q: MP.Queue[Tuple[MapCoord, Exception]],
        **kwargs,
    ):
        """
        :param args: Non-keyword arguments to pass to the superclass
        :param progress_proxy: A 'proxified' version of MapProgress
        :param progress_file: The path to which the Progress is to be saved
        :param coordfail_q: A queue containing failed Regions in the form of (Coordinate, Exception)
        :param kwargs: Keyword arguments to pass to the superclass
        """
        super().__init__(*args, **kwargs)
        self.incoming: MP.Queue[RecorderJob] = self.command_queue
        self.progress_proxy = progress_proxy
        self.progress_file = progress_file
        self.coordfail_q: MP.Queue[Tuple[MapCoord, Exception]] = coordfail_q

    def _flush(self, regions: dict[MapCoord, DominantColors]) -> None:
        """Updates the syncmanaged dict with values we gained. Including also fails."""
        failrows: Dict[int, None] = {}
        while not self.coordfail_q.empty():
            coord, ee = self.coordfail_q.get()
            failrows[coord.y] = None
        self.progress_proxy.failed_rows.update(failrows)
        self.progress_proxy.regions.update(regions)

    def _save(self, regions: dict[MapCoord, DominantColors]) -> None:
        """Flush then save the progress."""
        if not self.quiet:
            print("V", end="", flush=True)
        self._flush(regions)
        p = self.progress_proxy.unproxy()
        p.write_to_path(self.progress_file)

    def run(self) -> None:
        """Do multiprocessing jobs"""
        self.state = WorkerState.SETUP
        regions = copy.deepcopy(self.progress_proxy.regions)
        coord: Optional[MapCoord] = None
        ctrlc = False
        try:
            while True:
                self.state = WorkerState.READY
                try:
                    job: RecorderJob = self.incoming.get()
                except KeyboardInterrupt:
                    if not ctrlc:
                        ctrlc = True
                        continue
                    job = "DIE"

                if job == "DIE":
                    self.state = WorkerState.DYING
                    if not self.quiet:
                        print("Z", end="", flush=True)
                    break

                self.state = WorkerState.BUSY

                if job == "FLUSH":
                    self._flush(regions)
                    continue
                if job == "SAVE":
                    self._save(regions)
                    continue
                if isinstance(job, str):
                    print(f"\nUnrecognized command: {job}")
                    continue

                try:
                    assert isinstance(job, tuple)
                    assert len(job) == 2
                except AssertionError:
                    print(f"job is <{type(job)}> == {job}")
                    raise
                coord: MapCoord = job[0]
                domc: Optional[DominantColors] = job[1]

                if domc is None:
                    if coord in regions:
                        del regions[coord]
                    continue
                else:
                    regions[coord] = domc

                coord = None

        except (KeyboardInterrupt, Exception) as ee:
            if isinstance(coord, MapCoord):
                self.coordfail_q.put((coord, ee))
            if not isinstance(ee, KeyboardInterrupt):
                raise
        finally:
            self._save(regions)
            self.incoming.close()
            self.coordfail_q.close()
            self.state = WorkerState.DEAD
            time.sleep(1.0)
