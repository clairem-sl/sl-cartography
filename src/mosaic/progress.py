# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import multiprocessing as MP
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set

import msgpack

from mosaic.color_processing import DominantColors
from sl_maptools import MapCoord


@dataclass
class MosaicProgress:
    regions: Dict[MapCoord, DominantColors] = field(default_factory=dict)
    seen: Set[MapCoord] = field(default_factory=set)
    last_fail_rows: Set[int] = field(default_factory=set)

    def get_managed(self, mgr: MP.Manager):
        return (
            mgr.dict(self.regions),
            mgr.dict({k: None for k in self.seen}),
        )

    def write_to_stream(self, stream):
        encoded = {
            "__regions": [
                ((coord.x, coord.y), domc.encode())
                for coord, domc in self.regions.items()
            ],
            "__seen": [(coord.x, coord.y) for coord in self.seen],
            "__fails": list(self.last_fail_rows),
        }
        msgpack.pack(encoded, stream)

    def write_to_path(self, path: Path):
        with path.open("wb") as fout:
            self.write_to_stream(fout)

    @classmethod
    def new_from_stream(cls, stream):
        encoded = msgpack.unpack(stream)
        regions = {
            MapCoord(*coord): DominantColors.from_serialized(domc_raw)
            for coord, domc_raw in encoded["__regions"]
        }
        seen = set(MapCoord(*coord) for coord in encoded["__seen"])
        last_fail_rows = set(encoded["__fails"])
        return cls(regions=regions, seen=seen, last_fail_rows=last_fail_rows)

    @classmethod
    def new_from_path(cls, path: Path, missing_ok: bool = False):
        if not path.exists():
            if not missing_ok:
                raise FileNotFoundError(f"{path} not found!")
            return cls()
        with path.open("rb") as fin:
            return cls.new_from_stream(fin)
