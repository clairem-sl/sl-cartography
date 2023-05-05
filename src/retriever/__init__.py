import ruamel.yaml as ryaml

from collections import deque
from pathlib import Path
from typing import TypedDict, Generator, Final

from sl_maptools import MapCoord


class ProgressDict(TypedDict):
    max_unprocessed_y: int
    outstanding_coords: list[str]


class RetrieverProgress:
    DEFA_MIN: Final[int] = 0
    DEFA_MAX: Final[int] = 2100

    def __init__(
        self,
        backing_file: Path,
        auto_reset: bool = True,
        min_coord: MapCoord = MapCoord(DEFA_MIN, DEFA_MIN),
        max_coord: MapCoord = MapCoord(DEFA_MAX, DEFA_MAX),
    ):
        self.backing_file = backing_file
        self.auto_reset = auto_reset
        self.minc = min_coord
        self.maxc = max_coord
        self.max_unprocessed_y: int = max_coord.y
        self.to_dispatch: deque[tuple[int, int]] = deque()
        if backing_file.exists():
            self.load()
        self.to_retire: set[tuple[int, int]] = set()

    @property
    def outstanding_jobs(self) -> list[tuple[int, int]]:
        outstanding = set(self.to_retire)
        outstanding.update(self.to_dispatch)
        return sorted(outstanding, key=lambda t: (t[1], t[0]))

    @property
    def outstanding_count(self) -> int:
        return len(self.to_dispatch) + len(self.to_retire)

    def retire(self, item: tuple[int, int]):
        if item is None:
            return
        self.to_retire.discard(item)

    async def aretire(self, item: tuple[int, int]):
        if item is None:
            return
        self.retire(item)

    def load(self):
        with self.backing_file.open("rt") as fin:
            _last_sess: ProgressDict = ryaml.safe_load(fin)
        self.max_unprocessed_y = _last_sess["max_unprocessed_y"]
        if self.auto_reset and self.max_unprocessed_y < 0:
            self.max_unprocessed_y = 0
        _coords: set[tuple[int, int]] = set()
        for c in _last_sess.get("outstanding_coords", []):
            x, y = c.split(",")
            _coords.add((int(x), int(y)))
        self.to_dispatch.extend(sorted(_coords, key=lambda t: (t[1], t[0])))

    def save(self):
        exported: ProgressDict = {
            "max_unprocessed_y": self.max_unprocessed_y,
            "outstanding_coords": [f"{x},{y}" for x, y in self.outstanding_jobs],
        }
        with self.backing_file.open("wt") as fout:
            ryaml.dump(exported, fout, default_flow_style=False)

    async def abatch(self, batch_size: int) -> Generator[tuple[int, int], None, None]:
        for _ in range(batch_size):
            if not self.to_dispatch:
                if self.max_unprocessed_y < self.minc.y:
                    if not self.auto_reset:
                        return
                    self.max_unprocessed_y = self.maxc.y
                print(f"ROW:{self.max_unprocessed_y}", flush=True)
                self.to_dispatch = deque(
                    (x, self.max_unprocessed_y) for x in range(self.minc.x, self.maxc.x + 1)
                )
                self.max_unprocessed_y -= 1
            job = self.to_dispatch.popleft()
            self.to_retire.add(job)
            yield job
