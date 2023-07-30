# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pickle
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Final, NamedTuple

from sl_maptools import CoordType, RegionsDBRecord3

DB_PATH = Path(r"C:\Cache\SL-Carto\RegionsDB3.pkl")
CUTOFF = 3

# fmt: off
GRID_COLS: Final[list[str]] = [
    "AA", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U"
]
# fmt: on

_NAO = datetime.now().astimezone()

DATABASE: dict[CoordType, RegionsDBRecord3]


class InterestingRegion(NamedTuple):
    timestamp: datetime
    name: str
    coord: CoordType


def recent(max_days: int) -> set[InterestingRegion]:
    result: set[InterestingRegion] = set()
    for co, data in DATABASE.items():
        if not data["current_name"]:
            continue
        delta = _NAO - data["first_seen"]
        if delta.days <= max_days:
            d = InterestingRegion(data["first_seen"], data["current_name"], co)
            result.add(d)
    return result


def main():
    global DATABASE

    with DB_PATH.open("rb") as fin:
        DATABASE = pickle.load(fin)

    interesting: list[InterestingRegion] = sorted(recent(CUTOFF))
    print(f"{len(interesting)} new regions the past {CUTOFF} days")
    # new_areas: dict[str, list[CoordType]] = {}
    x_s: dict[str, set[int]] = defaultdict(set)
    y_s: dict[str, set[int]] = defaultdict(set)

    by_grid = []
    for i, (t, name, co) in enumerate(interesting, start=1):
        x, y = co
        col = x // 100
        row = y // 100
        gs = f"[{GRID_COLS[col]}{row}]"
        sco = f"{co}"
        by_grid.append((gs, sco, name))
        print(f"{i:>3}) {t.isoformat(timespec='minutes')} {sco:12} {gs:6} {name}")
        if 22 <= i <= 27:
            x_s["Silks"].add(x)
            y_s["Silks"].add(y)
        elif i >= 31:
            x_s["Azure"].add(x)
            y_s["Azure"].add(y)

    for k in x_s:
        print(f"{k}: {min(x_s[k])}-{max(x_s[k])}/{min(y_s[k])}-{max(y_s[k])}")
    print()

    print("Sorted by Grid then by Coordinates:")
    for i, (gs, sco, name) in enumerate(sorted(by_grid), start=1):
        print(f"{i:>3} {gs:6} {sco:12} {name}")


if __name__ == '__main__':
    main()
