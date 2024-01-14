# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from typing import ClassVar, Final

from worldmap_v4.nightlights2 import BeadedTilerBase


"""
  01234567
0 ···||···
1 ···||···
2 ··■■■■··
3 --■■■■--
4 --■■■■--
5 ··■■■■··
6 ···||···
7 ···||···
"""


class Tiler(BeadedTilerBase):
    """
    Creates a Nightlights tile (region) using the Beaded 8x8 strategy
    """
    Size: Final[int] = 8
    Center: ClassVar[tuple[int, int, int, int]] = (2, 2, 5, 5)
    Adjacent: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "N": (3, 0, 4, 1),
        "S": (3, 6, 4, 7),
        "W": (0, 3, 1, 4),
        "E": (6, 3, 7, 4),
    }
    Diag: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "NW": (0, 0, 2, 2),
        "NE": (5, 0, 7, 2),
        "SW": (0, 5, 2, 7),
        "SE": (5, 5, 7, 7),
    }
