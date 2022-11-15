# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import copy
import multiprocessing as MP
import time
from pathlib import Path
from typing import Dict, Optional

from mosaic_v3.color_processing import DominantColors
from mosaic_v3.progress import MosaicProgressProxy
from mosaic_v3.workers import Worker, WorkerState
from sl_maptools import MapCoord


class TileRecorder(Worker):
    MIN_SAVE_DISTANCE = 200

    def __init__(
        self,
        *args,
        progress_proxy: MosaicProgressProxy,
        progress_file: Path,
        coordfail_q: MP.Queue,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.incoming = self.command_queue
        self.progress_proxy = progress_proxy
        self.progress_file = progress_file
        self.coordfail_q = coordfail_q

    def _flush(self, regions):
        failrows: Dict[int, None] = {}
        while not self.coordfail_q.empty():
            coord: MapCoord = self.coordfail_q.get()
            failrows[coord.y] = None
        self.progress_proxy.failed_rows.update(failrows)
        self.progress_proxy.regions.update(regions)

    def _save(self, regions):
        self._flush(regions)
        p = self.progress_proxy.unproxy()
        p.write_to_path(self.progress_file)

    def run(self) -> None:
        self.state = WorkerState.SETUP
        regions = copy.deepcopy(self.progress_proxy.regions)
        coord: Optional[MapCoord] = None
        try:
            while True:
                self.state = WorkerState.READY
                job = self.incoming.get()

                if job == "DIE":
                    self.state = WorkerState.DYING
                    self._save(regions)
                    print("Z", end="", flush=True)
                    break

                self.state = WorkerState.BUSY

                if job == "FLUSH":
                    self._flush(regions)
                    continue
                if job == "SAVE":
                    if not self.quiet:
                        print("V", end="", flush=True)
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
            # noinspection PyBroadException
            try:
                self.state = WorkerState.DEAD
                self.incoming.close()
                self.coordfail_q.close()
                time.sleep(1.0)
            except Exception:
                pass
