from __future__ import annotations

import pickle
from pathlib import Path
from typing import Callable


class FileBackedData:
    def __init__(self, backing_file: Path, default_factory: Callable):
        self.fp = backing_file
        self._factory = default_factory
        self._data = None

    def load(self):
        if self.fp.exists():
            with self.fp.open("rb") as fin:
                self._data = pickle.load(fin)
        else:
            self._data = self._factory()

    def save(self):
        with self.fp.open("wb") as fout:
            pickle.dump(self._data, fout, protocol=pickle.HIGHEST_PROTOCOL)
