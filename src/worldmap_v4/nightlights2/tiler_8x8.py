# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from typing import ClassVar, Final

from PIL import Image, ImageDraw

from sl_maptools import MapCoord
from worldmap_v4.nightlights2 import TilerBase


class Tiler(TilerBase):
    Size: Final[int] = 8

    _Adjacent: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "N": (3, 0, 4, 1),
        "S": (3, 6, 4, 7),
        "W": (0, 3, 1, 4),
        "E": (6, 3, 7, 4),
    }
    _Diag: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "NW": (0, 0, 2, 2),
        "NE": (5, 0, 7, 2),
        "SW": (0, 5, 2, 7),
        "SE": (5, 5, 7, 7),
    }
    _Rounder: ClassVar[dict[str, tuple[int, int]]] = {
        "NW": (5, 5),
        "NE": (2, 5),
        "SW": (5, 2),
        "SE": (2, 2),
    }

    def maketile(self, coord: MapCoord) -> Image:
        """
        Makes a tile of the region at (x, y) considering its neighbors
        """
        cls = self.__class__
        tile = Image.new("L", (self.Size, self.Size))
        draw = ImageDraw.Draw(tile)
        draw.rectangle((2, 2, 5, 5), fill=255)
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
