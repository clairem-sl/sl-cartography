# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from typing import ClassVar, Final

from PIL import Image, ImageDraw

from sl_maptools import MapCoord
from worldmap_v4.nightlights2 import TilerBase

"""
  0123456789
0 ··········
1 ··········
2 ··········
3 ···■■■■···
4 ···■■■■···
5 ···■■■■···
6 ···■■■■···
7 ··········
8 ··········
9 ··········
"""


class Tiler(TilerBase):
    Size: Final[int] = 10

    _Adjacent: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "N": (4, 0, 5, 2),
        "S": (4, 7, 5, 9),
        "W": (0, 4, 2, 5),
        "E": (7, 4, 9, 5),
    }
    _Diag: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "NW": (0, 0, 3, 3),
        "NE": (6, 0, 9, 3),
        "SW": (0, 6, 3, 9),
        "SE": (6, 6, 9, 9),
    }
    _Rounder: ClassVar[dict[str, tuple[int, int]]] = {
        "NW": (6, 6),
        "NE": (3, 6),
        "SW": (6, 3),
        "SE": (3, 3),
    }

    def maketile(self, coord: MapCoord) -> Image:
        """
        Makes a tile of the region at (x, y) considering its neighbors
        """
        cls = self.__class__
        tile = Image.new("L", (self.Size, self.Size))
        draw = ImageDraw.Draw(tile)
        draw.rectangle((3, 3, 6, 6), fill=255)
        neighs = self.get_neighbors(coord)
        if not neighs:
            return tile
        for compass, box in cls._Adjacent.items():
            if compass in neighs:
                draw.rectangle(box, fill=255)
        for compass, box in cls._Diag.items():
            cs = {compass, compass[0], compass[1]}
            if cs.issubset(neighs):
                draw.rectangle(box, fill=255)
            if not self._round:
                continue
            if cs == neighs:
                draw.point(cls._Rounder[compass], fill=0)
        return tile
