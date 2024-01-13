
from typing import ClassVar, Final

from PIL import Image, ImageDraw

from sl_maptools import MapCoord
from worldmap_v4.nightlights2 import TilerBase


class Tiler(TilerBase):
    Size: Final[int] = 7

    _Adjacent: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "N": (3, 0, 5, 2),
        "S": (3, 6, 5, 8),
        "W": (0, 3, 2, 5),
        "E": (6, 3, 8, 5),
    }
    _Diag: ClassVar[dict[str, tuple[int, int, int, int]]] = {
        "NW": (0, 0, 3, 3),
        "NE": (5, 0, 8, 3),
        "SW": (0, 5, 3, 8),
        "SE": (5, 5, 8, 8),
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
        color = {"fill": 255, "outline": 255}
        draw.rectangle((2, 2, 6, 6), **color)
        neighs = self.get_neighbors(coord)
        if not neighs:
            return tile
        for compass, box in cls._Adjacent.items():
            if compass in neighs:
                draw.rectangle(box, **color)
        for compass, box in cls._Diag.items():
            cs = {compass, compass[0], compass[1]}
            if cs.issubset(neighs):
                draw.rectangle(box, **color)
            if not self._round:
                continue
            if cs == neighs:
                draw.point(cls._Rounder[compass], fill=0)
        return tile
