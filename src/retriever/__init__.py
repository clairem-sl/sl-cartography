import ruamel.yaml as ryaml

from collections import deque
from pathlib import Path
from typing import TypedDict, Generator, Final

from sl_maptools import MapCoord


class ProgressDict(TypedDict):
    next_x: int
    next_y: int
    outstanding: list[str]


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
        self.next_x = min_coord[0]
        self.next_y = max_coord[1]
        self.outstanding: set[tuple[int, int]] = set()
        self._backlog: deque[tuple[int, int]] = deque()
        if backing_file.exists():
            self.load()

    @property
    def outstanding_jobs(self) -> list[tuple[int, int]]:
        return sorted(self.outstanding, key=lambda t: (t[1], t[0]))

    @property
    def outstanding_count(self) -> int:
        return len(self.outstanding)

    def retire(self, item: tuple[int, int]):
        if item is None:
            return
        self.outstanding.discard(item)

    async def aretire(self, item: tuple[int, int]):
        if item is None:
            return
        self.retire(item)

    def load(self):
        with self.backing_file.open("rt") as fin:
            _last_sess: ProgressDict = ryaml.safe_load(fin)
        self.next_x = _last_sess.get("next_x", self.minc[0])
        self.next_y = _last_sess.get("next_y", self.maxc[1])
        for c in _last_sess.get("outstanding", []):
            x, y = c.split(",")
            self.outstanding.add((int(x), int(y)))
        self._backlog.extend(self.outstanding_jobs)

    def save(self):
        exported: ProgressDict = {
            "next_x": self.next_x,
            "next_y": self.next_y,
            "outstanding": [f"{x},{y}" for x, y in self.outstanding_jobs],
        }
        with self.backing_file.open("wt") as fout:
            ryaml.dump(exported, fout, default_flow_style=False)

    async def abatch(self, batch_size: int) -> Generator[tuple[int, int], None, None]:
        c = 0
        while self._backlog:
            c += 1
            yield self._backlog.popleft()
            if c >= batch_size:
                return
        while c < batch_size:
            while True:
                job = self.next_x, self.next_y
                if job not in self.outstanding:
                    c += 1
                    self.outstanding.add(job)
                    yield job
                self.next_x += 1
                if self.next_x > self.maxc[0]:
                    self.next_x = self.minc[0]
                    self.next_y -= 1
                    if self.next_y < self.minc[1]:
                        if not self.auto_reset:
                            return
                        self.next_y = self.maxc[1]
                    print(f"ROW:{job[1]}", flush=True)
