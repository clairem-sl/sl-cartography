# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from itertools import combinations
from typing import TYPE_CHECKING

from sl_maptools.knowns import KNOWN_AREAS

if TYPE_CHECKING:
    from sl_maptools import AreaBounds


def main() -> None:  # noqa: D103
    areas = list(KNOWN_AREAS.items())
    na1: tuple[str, AreaBounds]
    na2: tuple[str, AreaBounds]
    for na1, na2 in combinations(areas, 2):
        n1, a1 = na1
        n2, a2 = na2
        if (inter := a1.intersection(a2)) is not None:
            print(f"{n1} ∩ {n2} = {inter!r}")


if __name__ == "__main__":
    main()
