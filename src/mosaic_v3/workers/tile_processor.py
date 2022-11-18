# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import io
import multiprocessing as MP
from typing import Literal, Optional, Tuple, Union

from PIL import Image

from mosaic_v3.color_processing import DominantColors
from mosaic_v3.workers import Worker, WorkerState
from mosaic_v3.workers.recorder import RecorderJob
from sl_maptools import MapCoord, MapTile
from sl_maptools.fetcher import RawTile


ProcessorSignals = Union[Literal["DIE"], Literal["SAVE"]]
ProcessorJob = Union[ProcessorSignals, RawTile]


class TileProcessor(Worker):
    """
    Processes tiles received through the input/command queue.

    This class implements the logic that processes tiles received through the input/command queue.

    Currently, the process is just one: To find out the dominant color of every tile.
    The logic/maths to do that is implemented in the DominantColors class.

    This class recognizes the following 'jobs' in the input/command queue:
    - "DIE" instruction to wrap up and end
    - "SAVE" instruction to save progress so far -- will be passed through to Recorder
    - MapTile -- actual fetched tile, will start the DominantColors processing
    """

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
        coord: Optional[MapCoord] = None
        try:
            while True:
                self.state = WorkerState.READY
                job: ProcessorJob = self.input_q.get()

                self.state = WorkerState.BUSY
                if job is None:
                    continue
                if job == "DIE":
                    self.state = WorkerState.DYING
                    if not self.quiet:
                        print("X", end="", flush=True)
                    break
                if job == "SAVE":
                    if not self.quiet:
                        print(">S>", end="", flush=True)
                    self.output_q.put("SAVE")
                    continue
                if isinstance(job, str):
                    print(f"Unknown command: {job}")
                    continue
                if not isinstance(job, tuple):
                    print(f"Unknown job <{type(job)}>: {job}")
                    continue

                coord, rawdata = job
                try:
                    if rawdata:
                        with io.BytesIO(rawdata) as bio:
                            img = Image.open(bio)
                            img.load()
                        domc = DominantColors.from_tile(MapTile(coord, img))
                    else:
                        domc = None
                    self.output_q.put((coord, domc))
                except Exception as ew:
                    errmess = f"ERR[{type(ew)}:{ew}]({coord.x},{coord.y})"
                    print(errmess, end="", flush=True)
                    self.err_q.put(errmess)
                    self.coordfail_q.put_nowait((coord, ew))

                count += 1
                if count >= 100:
                    if not self.quiet:
                        print("*", end="", flush=True)
                    count = 0
        except (KeyboardInterrupt, Exception) as ee:
            self.coordfail_q.put((coord, ee))
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
