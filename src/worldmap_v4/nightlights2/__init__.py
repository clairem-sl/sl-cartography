# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from abc import ABCMeta, abstractmethod
from typing import ClassVar, Final

from PIL import Image, ImageDraw

from sl_maptools import MapCoord


class TilerBase(metaclass=ABCMeta):
    """Abstract class for classes that creates region tiles"""

    Size: int

    _Neighbors: Final[ClassVar[dict[tuple[int, int], str]]] = {
        (0, -1): "S",
        (-1, 0): "W",
        (1, 0): "E",
        (0, 1): "N",
        (1, 1): "NE",
        (-1, -1): "SW",
        (1, -1): "SE",
        (-1, 1): "NW",
    }

    def __init__(self, region_set: set[MapCoord]):
        """
        :param region_set: Region Databse
        """
        self._regs = region_set
        self._round = True

    def get_neighbors(self, coord: MapCoord) -> set[str]:
        """
        Get existing neighbors of a region at (x, y)

        :param coord: Geo-coordinate of the region
        :return: A set of compass points representing existing neighbors
        """
        return {compass for offset, compass in self.__class__._Neighbors.items() if (coord + offset) in self._regs}

    @abstractmethod
    def maketile(self, coord: MapCoord) -> Image:
        """
        Makes a tile of the region at (x, y) considering its neighbors
        """
        ...


class BeadedTilerBase(TilerBase, metaclass=ABCMeta):
    """
    Abstract Base Class for tilers that uses the "beaded" drawing strategy
    """
    Center: ClassVar[tuple[int, int, int, int]] = (0, 0, 0, 0)
    Adjacent: ClassVar[dict[str, tuple[int, int, int, int]]] = {}
    Diag: ClassVar[dict[str, tuple[int, int, int, int]]] = {}
    Rounders: ClassVar[dict[str, tuple[int, int]]] = {}

    @property
    def rounders(self):
        """
        Returns a dict of where to put 'rounding' pixels given a compass coordinate
        """
        cls = self.__class__
        if not cls.Rounders:
            x1, y1, x2, y2 = cls.Center
            cls.Rounders = {
                "NW": (x2, y2),
                "NE": (x1, y2),
                "SW": (x2, y1),
                "SE": (x1, y1),
            }
        return cls.Rounders

    def maketile(self, coord: MapCoord) -> Image:
        """
        Makes a tile of the region at (x, y) considering its neighbors
        """
        cls = self.__class__
        if not (cls.Adjacent and cls.Diag):
            raise RuntimeError("BeadedTile.Adjacent and/or BeadedTile.Diag are not initialized!")

        x1, y1, x2, y2 = cls.Center

        if x1 == y1 == x2 == y2:
            raise RuntimeError("BeadedTile.Center is not initialized!")

        tile = Image.new("L", (self.Size, self.Size))
        draw = ImageDraw.Draw(tile)
        draw.rectangle(cls.Center, fill=255)
        if not (neighs := self.get_neighbors(coord)):
            return tile

        for compass, box in cls.Adjacent.items():
            if compass in neighs:
                draw.rectangle(box, fill=255)
        rounders = self.rounders
        for compass, box in cls.Diag.items():
            cs = {compass, compass[0], compass[1]}
            if cs.issubset(neighs):
                draw.rectangle(box, fill=255)
            if not self._round:
                continue
            if cs == neighs:
                draw.point(rounders[compass], fill=0)
        return tile
