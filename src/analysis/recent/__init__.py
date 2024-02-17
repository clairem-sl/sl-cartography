# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import pickle
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pathlib import Path

    from sl_maptools import CoordType, RegionsDBRecord3

_NAO = datetime.now().astimezone()


class InterestingRegion(NamedTuple):
    """A record of interesting regions"""

    timestamp: datetime
    name: str
    coord: CoordType


def recent(db_path: Path, max_days: int) -> set[InterestingRegion]:
    """Returns a set of interesting regions with age <= max_days"""
    with db_path.open("rb") as fin:
        database: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)  # noqa: S301

    result: set[InterestingRegion] = set()
    for co, data in database.items():
        if not data["current_name"]:
            continue
        delta = _NAO - data["first_seen"]
        if delta.days <= max_days:
            d = InterestingRegion(data["first_seen"], data["current_name"], co)
            result.add(d)
    return result
