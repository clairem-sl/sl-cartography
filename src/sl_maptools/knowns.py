# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import sys

from pathlib import Path
from typing import Final

if sys.version_info < (3, 11):
    from typing_extensions import NotRequired, TypedDict
else:
    from typing import NotRequired, TypedDict

from ruamel.yaml import YAML

from sl_maptools import AreaBounds, AreaDescriptor

# fmt: off
DO_NOT_MAP_AREAS: Final[dict[str, AreaBounds]] = {
    "CH": AreaBounds(1102, 1199, 1104, 1201),        ### NOT interesting
    "SSP-15xx": AreaBounds(1155, 1379, 1165, 1383),  ### NOT interesting
    "SSP-40xx": AreaBounds(1182, 1371, 1187, 1377),  ### NOT interesting
}

# fmt: on

KNOWN_AREAS: Final[dict[str, AreaDescriptor]] = {}


CoordBounds = list[str | list[int]]


class AreaDef(TypedDict):
    includes: CoordBounds
    excludes: NotRequired[CoordBounds]
    slgi_url: NotRequired[str]
    alternative_names: NotRequired[list[str]]
    notes: NotRequired[str]


def read_known_areas(yaml_file: Path):
    KNOWN_AREAS.clear()
    _data: dict[str, AreaDef]
    with yaml_file.open("rt") as fin:
        _data = YAML(typ="safe").load(fin)

    def _to_abounds(item) -> AreaBounds:
        if isinstance(item, str):
            return AreaBounds.from_slgi(item)
        if isinstance(item, list) and len(item) == 4:
            return AreaBounds(*item)
        raise ValueError(f"Don't understand this item: {item}")

    for _n, _d in _data.items():
        _incs = {_to_abounds(i) for i in _d["includes"]}
        _excs = {_to_abounds(i) for i in _d.get("excludes", [])}
        KNOWN_AREAS[_n] = AreaDescriptor(includes=_incs, excludes=_excs, name=_n)


read_known_areas(Path(__file__).with_suffix(".yaml"))
