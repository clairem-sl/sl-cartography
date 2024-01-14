# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from typing import ClassVar, Final

from worldmap_v4.nightlights2 import BeadedTilerBase

"""
  0123456789
0 ····||····
1 ····||····
2 ····||····
3 ···■■■■···
4 ---■■■■---
5 ---■■■■---
6 ···■■■■···
7 ····||····
8 ····||····
9 ····||····
"""


class Tiler(BeadedTilerBase):
    """
    Creates a Nightlights tile (region) using the Beaded 10x10 strategy
    """
    Size: Final[int] = 10
    Center: ClassVar[tuple[int, int, int, int]] = (3, 3, 6, 6)
    Adjacent: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "N": (4, 0, 5, 2),
        "S": (4, 7, 5, 9),
        "W": (0, 4, 2, 5),
        "E": (7, 4, 9, 5),
    }
    Diag: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "NW": (0, 0, 3, 3),
        "NE": (6, 0, 9, 3),
        "SW": (0, 6, 3, 9),
        "SE": (6, 6, 9, 9),
    }
