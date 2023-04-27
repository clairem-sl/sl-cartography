# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
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


class JobsSet(FileBackedData):
    def __init__(self, backing_file: Path):
        super().__init__(backing_file, set)
        self._data: set[tuple[int, int]] = set()
        self.load()

    def add(self, item):
        self._data.add(item)

    def remove(self, item):
        self._data.remove(item)

    def discard(self, element):
        self._data.discard(element)

    def update(self, iterable):
        self._data.update(iterable)

    def clear(self):
        self._data.clear()

    def __len__(self):
        return len(self._data)

    def __contains__(self, item):
        return item in self._data

    def __iter__(self):
        return self._data.__iter__()
