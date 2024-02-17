# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

from analysis.recent import InterestingRegion, recent
from sl_maptools.config import DefaultConfig as Config

if TYPE_CHECKING:
    from sl_maptools import CoordType

DEFA_CUTOFF = 6

# fmt: off
GRID_COLS: Final[list[str]] = [
    "AA", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U"
]
# fmt: on


class Options(Protocol):
    """Represent options extracted from command line"""

    cutoff: int


def _get_options() -> Options:
    """Extract options from CLI"""
    parser = argparse.ArgumentParser()

    parser.add_argument("--cutoff", type=int, default=DEFA_CUTOFF)

    return cast(Options, parser.parse_args())


def main(opts: Options) -> None:  # noqa: D103
    db_path = Path(Config.names.dir) / Config.names.db
    interesting: list[InterestingRegion] = sorted(recent(db_path, opts.cutoff))
    print(f"{len(interesting)} new regions the past {opts.cutoff} days")
    # new_areas: dict[str, list[CoordType]] = {}
    x_s: dict[str, set[int]] = defaultdict(set)
    y_s: dict[str, set[int]] = defaultdict(set)

    by_grid = []
    t: datetime
    name: str
    co: CoordType
    for i, (t, name, co) in enumerate(interesting, start=1):
        x, y = co
        col = x // 100
        row = y // 100
        gs = f"[{GRID_COLS[col]}{row}]"
        sco = f"{co}"
        age = (datetime.now().astimezone() - t).days
        # age = 0
        by_grid.append((gs, sco, name, age))
        print(f"{i:>3}) {t.isoformat(timespec='minutes')} {sco:12} {gs:6} {name}")
        # if 22 <= i <= 27:
        #     x_s["Silks"].add(x)
        #     y_s["Silks"].add(y)
        # elif i >= 31:
        #     x_s["Azure"].add(x)
        #     y_s["Azure"].add(y)

    for k in x_s:
        print(f"{k}: {min(x_s[k])}-{max(x_s[k])}/{min(y_s[k])}-{max(y_s[k])}")
    print()

    print("Sorted by Grid then by Coordinates:")
    for i, (gs, sco, name, age) in enumerate(sorted(by_grid), start=1):
        print(f"{i:>3} {gs:6} {sco:12} [{age}d] {name}")


if __name__ == "__main__":
    main(_get_options())
