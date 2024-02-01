# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, NamedTuple, Protocol, cast
from zoneinfo import ZoneInfo

from sl_maptools import CoordType, RegionsDBRecord3
from sl_maptools.utils import ConfigReader

Config = ConfigReader(r"C:\Cache\SL-Carto\RegionsDB3.pkl")

DB_PATH = Path(Config.names.dir) / Config.names.db
DEFA_CUTOFF = 6

# fmt: off
GRID_COLS: Final[list[str]] = [
    "AA", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U"
]
# fmt: on

_NAO = datetime.now().astimezone()


class Options(Protocol):
    """Represent options extracted from command line"""

    cutoff: int


def get_options() -> Options:
    """Extract options from CLI"""
    parser = argparse.ArgumentParser()

    parser.add_argument("--cutoff", type=int, default=DEFA_CUTOFF)

    return cast(Options, parser.parse_args())


class InterestingRegion(NamedTuple):
    """A record of interesting regions"""

    timestamp: datetime
    name: str
    coord: CoordType


def recent(max_days: int) -> set[InterestingRegion]:
    """Returns a set of interesting regions with age <= max_days"""
    with DB_PATH.open("rb") as fin:
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


def main(opts: Options) -> None:  # noqa: D103
    interesting: list[InterestingRegion] = sorted(recent(opts.cutoff))
    print(f"{len(interesting)} new regions the past {opts.cutoff} days")
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
        age = (cast(timedelta, datetime.now(tz=ZoneInfo("Asia/Jakarta")) - t)).days
        # age = 0
        by_grid.append((gs, sco, name, age))
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
    for i, (gs, sco, name, age) in enumerate(sorted(by_grid), start=1):
        print(f"{i:>3} {gs:6} {sco:12} [{age}d] {name}")


if __name__ == "__main__":
    main(get_options())
