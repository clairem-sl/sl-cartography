# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import shutil

try:
    # noinspection PyCompatibility
    import tomllib
except ModuleNotFoundError:
    # noinspection PyUnresolvedReferences
    import tomli as tomllib

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


def make_backup(the_file: Path, levels: int = 2):
    if not the_file.exists():
        return
    suff = the_file.suffix
    # prev0 is temporary; the loop will rename it to prev1
    shutil.copy(the_file, the_file.with_suffix(".prev0" + suff))
    for n in range(levels, 0, -1):
        prev_n = the_file.with_suffix(f".prev{n}{suff}")
        prev_b = the_file.with_suffix(f".prev{n-1}{suff}")
        if prev_b.exists():
            prev_b.replace(prev_n)


class QuietablePrint:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def __call__(self, *args, **kwargs):
        if not self.quiet:
            print(*args, **kwargs)


class ValueTree:
    def __init__(self, data: dict):
        self.__data = data

    def __getattr__(self, item):
        if item not in self.__data:
            raise KeyError(f"Not Found: {item}")
        value = self.__data[item]
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return ValueTree(value)
        if isinstance(value, Sequence):
            return ValueTree.__process_seq(value)
        else:
            return value

    def __getitem__(self, item):
        return self.__getattr__(item)

    @staticmethod
    def __process_seq(seq: Sequence):
        rslt = []
        for thing in seq:
            if not isinstance(thing, str) and isinstance(thing, Sequence):
                rslt.append(ValueTree.__process_seq(thing))
            elif isinstance(thing, dict):
                rslt.append(ValueTree(thing))
            else:
                rslt.append(thing)
        return rslt

    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.__data)}"


class NamesConfig(Protocol):
    dir: str
    db: str
    lock: str
    log: str
    progress: str


class MapsConfig(Protocol):
    dir: str
    lock: str
    log: str
    progress: str


class MosaicConfig(Protocol):
    domc_cache: str


class AreasConfig(Protocol):
    dir: str


class GridsConfig(Protocol):
    dir_composite: str
    dir_overlay: str
    font_name: str
    font_size: int


class SLMapToolsConfig(Protocol):
    names: NamesConfig
    maps: MapsConfig
    mosaic: MosaicConfig
    areas: AreasConfig
    grids: GridsConfig


class ConfigReader(SLMapToolsConfig):
    def __init__(self, config_file: str | Path):
        self._cfg_file = Path(config_file)
        with self._cfg_file.open("rb") as fin:
            self._cfg_dict = tomllib.load(fin)
        self._cfg_tree = ValueTree(self._cfg_dict)

    def __getattr__(self, item):
        return getattr(self._cfg_tree, item)

    def __getitem__(self, item):
        return self._cfg_tree[item]

    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self._cfg_file)})"
