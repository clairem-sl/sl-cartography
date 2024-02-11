# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from pathlib import Path
from typing import Final

from typing import NotRequired, TypedDict

from ruamel.yaml import YAML

from sl_maptools import AreaBounds, AreaDescriptor, AreaDescriptorMeta

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
    """Semantics of the YAML file to read"""

    includes: CoordBounds
    excludes: NotRequired[CoordBounds]
    meta: NotRequired[AreaDescriptorMeta]
    slgi_url: NotRequired[str]
    alternative_names: NotRequired[list[str]]
    notes: NotRequired[str]


def read_known_areas(yaml_file: Path) -> None:
    """Read a YAML file and put the contents in KNOWN_AREAS"""
    KNOWN_AREAS.clear()
    _data: dict[str, AreaDef]
    with yaml_file.open("rt") as fin:
        _data = YAML(typ="safe").load(fin)

    def _to_abounds(item: str | list[int]) -> AreaBounds:
        if isinstance(item, str):
            return AreaBounds.from_slgi(item)
        if isinstance(item, list) and len(item) == 4:  # noqa: PLR2004
            return AreaBounds(*item)
        raise ValueError(f"Don't understand this item: {item}")

    for _n, _d in _data.items():
        _incs = {_to_abounds(i) for i in _d["includes"]}
        _excs = {_to_abounds(i) for i in _d.get("excludes", [])}
        _meta = _d.get("meta")
        KNOWN_AREAS[_n] = AreaDescriptor(includes=_incs, excludes=_excs, name=_n, meta=_meta)


read_known_areas(Path(__file__).with_suffix(".yaml"))
