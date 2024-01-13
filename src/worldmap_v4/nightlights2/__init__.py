# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from abc import ABCMeta, abstractmethod
from typing import ClassVar

from PIL import Image

from sl_maptools import MapCoord


class TilerBase(metaclass=ABCMeta):
    """Abstract class for classes that creates region cells"""
    Size: int

    _Neighbors: ClassVar[dict[tuple[int, int], str]] = {
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
        return {
            compass
            for offset, compass in self.__class__._Neighbors.items()
            if (coord + offset) in self._regs
        }

    @abstractmethod
    def maketile(self, coord: MapCoord) -> Image:
        """
        Makes a tile of the region at (x, y) considering its neighbors
        """
        ...
