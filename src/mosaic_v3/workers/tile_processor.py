# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import multiprocessing as MP
from typing import Optional, Tuple, Union

from mosaic_v3.color_processing import DominantColors
from mosaic_v3.workers import Worker, WorkerState
from mosaic_v3.workers.recorder import RecorderJob
from sl_maptools import MapCoord, MapTile


ProcessorJob = Union[str, MapTile]


class TileProcessor(Worker):
    SAVE_SIGNALS = {"SAVE", "ROW"}

    def __init__(
        self,
        *args,
        output_q: MP.Queue[RecorderJob],
        coordfail_q: MP.Queue[Tuple[MapCoord, Exception]],
        err_q: MP.Queue[str],
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.input_q: MP.Queue[ProcessorJob] = self.command_queue
        self.output_q = output_q
        self.err_q = err_q
        self.coordfail_q = coordfail_q

    def run(self) -> None:
        self.state = WorkerState.SETUP
        count = 0
        tile: Optional[MapTile] = None
        try:
            while True:
                self.state = WorkerState.READY
                job: ProcessorJob = self.input_q.get()

                self.state = WorkerState.BUSY
                if job is None:
                    continue
                if job == "DIE":
                    self.state = WorkerState.DYING
                    print("X", end="", flush=True)
                    break
                if job in self.SAVE_SIGNALS:
                    self.output_q.put("SAVE")
                    continue
                if isinstance(job, str):
                    print(f"Unknown command: {job}")
                    continue
                if not isinstance(job, MapTile):
                    print(f"Unknown job <{type(job)}>: {job}")
                    continue

                tile = job
                try:
                    if not tile.is_void:
                        domc = DominantColors.from_tile(tile)
                    else:
                        domc = None
                    self.output_q.put((tile.coord, domc))
                except Exception as ew:
                    errmess = f"ERR[{type(ew)}:{ew}]({tile.coord.x},{tile.coord.y})"
                    print(errmess, end="", flush=True)
                    self.err_q.put(errmess)
                    self.coordfail_q.put_nowait((tile.coord, ew))
                else:
                    tile = None

                count += 1
                if count >= 100:
                    if not self.quiet:
                        print("*", end="", flush=True)
                    count = 0
        except (KeyboardInterrupt, Exception) as ee:
            if isinstance(tile, MapTile):
                self.coordfail_q.put((tile.coord, ee))
            if not isinstance(ee, KeyboardInterrupt):
                raise
        finally:
            # noinspection PyBroadException
            try:
                self.state = WorkerState.DEAD
                self.input_q.close()
                self.output_q.close()
                self.err_q.close()
                self.coordfail_q.close()
            except Exception:
                pass
