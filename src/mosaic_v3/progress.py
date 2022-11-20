# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import copy
import multiprocessing as MP
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, Self, Set, Tuple, TypedDict

import msgpack

from mosaic_v3.color_processing import DominantColors
from sl_maptools import MapCoord


class MosaicProgressSerialized(TypedDict):
    __regions: Iterable[Tuple[Tuple[int, int], Dict[str, Tuple[int, int, int]]]]
    __completed: Iterable[int]
    __fails: Iterable[int]


@dataclass
class MosaicProgress:
    """
    Tracks the progress of world map building.

    This class is serializable using MessagePack. The decision to use MessagePack instead of plain ol' pickle is
    because with pickle, if we refactor the code by moving this class around, pickle might fail to re-instantiate
    the object as stored. MessagePack provides a location-agnostic mechanism to serialize and unserialize.

    Also, this class records DominantColors of each MapCoord for Mosaic-making purposes, hence the name of the
    class, "MosaicProgress".
    """

    regions: Dict[MapCoord, DominantColors] = field(default_factory=dict)
    completed_rows: Set[int] = field(default_factory=set)
    failed_rows: Set[int] = field(default_factory=set)

    def write_to_stream(self, stream: BinaryIO) -> None:
        """Serializes the class into an already-open binary 'file' (or file-like stream.)"""
        encoded: MosaicProgressSerialized = {
            "__regions": [(coord.encode(), domc.encode()) for coord, domc in self.regions.items()],
            "__completed": list(self.completed_rows),
            "__fails": list(self.failed_rows),
        }
        msgpack.pack(encoded, stream)

    def write_to_path(self, path: Path, with_temp: bool = True) -> None:
        """Serializes the class into a file."""
        if not with_temp:
            with path.open("wb") as fout:
                self.write_to_stream(fout)
        else:
            suff = path.suffix
            temp = path.with_suffix(".temp" + suff)
            with temp.open("wb") as fout:
                self.write_to_stream(fout)
            temp.replace(path)

    @classmethod
    def new_from_stream(cls, stream: BinaryIO) -> Self:
        """Re-instantiates the class from an already-open binary 'file' (or file-like object.)"""
        encoded: MosaicProgressSerialized = msgpack.unpack(stream)
        regions = {
            MapCoord(*coord): DominantColors.from_serialized(domc_raw) for coord, domc_raw in encoded["__regions"]
        }
        completed = set(encoded["__completed"])
        failed_rows = set(encoded["__fails"])
        return cls(regions=regions, completed_rows=completed, failed_rows=failed_rows)

    @classmethod
    def new_from_path(cls, path: Path, missing_ok: bool = False) -> Self:
        """Re-instantiates the class from a file."""
        if not path.exists():
            if not missing_ok:
                raise FileNotFoundError(f"{path} not found!")
            return cls()
        with path.open("rb") as fin:
            return cls.new_from_stream(fin)

    def deepcopy(self) -> MosaicProgress:
        """Perform a deepcopy() of a MosaicProgress object."""
        regs = copy.deepcopy(self.regions)
        seen = copy.deepcopy(self.completed_rows)
        fail = copy.deepcopy(self.failed_rows)
        return MosaicProgress(regions=regs, completed_rows=seen, failed_rows=fail)

    def get_proxies(self, mgr: MP.managers.SyncManager) -> MosaicProgressProxy:
        """Get a 'proxified' version of MosaicProgress, i.e., something synced by a SyncManager."""
        return MosaicProgressProxy(
            mgr.dict(self.regions),
            mgr.dict({k: None for k in self.completed_rows}),
            mgr.dict({k: None for k in self.failed_rows}),
        )


@dataclass(frozen=True)
class MosaicProgressProxy:
    regions: Dict[MapCoord, DominantColors]
    completed_rows: Dict[int, None]
    failed_rows: Dict[int, None]

    def unproxy(self) -> MosaicProgress:
        return MosaicProgress(
            regions=self.regions.copy(),
            completed_rows=set(self.completed_rows.keys()),
            failed_rows=set(self.failed_rows.keys()),
        )

    @classmethod
    def proxify(cls, prog: MosaicProgress, mgr: MP.managers.SyncManager) -> Self:
        return cls(
            mgr.dict(prog.regions),
            mgr.dict({k: None for k in prog.completed_rows}),
            mgr.dict({k: None for k in prog.failed_rows}),
        )
