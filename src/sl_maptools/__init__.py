# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple, Optional

from PIL import Image


class AreaBounds(NamedTuple):
    """
    Boundaries of an area, usually in terms of Map Coordinates
    """
    x_westmost: int
    y_southmost: int
    x_eastmost: int
    y_northmost: int

    def __contains__(self, item: tuple[int, int]) -> bool:
        x, y = item
        return (self.x_westmost <= x <= self.x_eastmost) and (
                self.y_southmost <= y <= self.y_northmost
        )

    @property
    def height(self):
        """Height of map in Units of Regions"""
        return self.y_northmost - self.y_southmost + 1

    @property
    def width(self):
        """Width of map in Units of Regions"""
        return self.x_eastmost - self.x_westmost + 1

    @classmethod
    def from_coords(cls, coord1: tuple[int, int], coord2: tuple[int, int]):
        x1, y1 = coord1
        x2, y2 = coord2
        x_min, x_max = (x1, x2) if x1 <= x2 else (x2, x1)
        y_min, y_max = (y1, y2) if y1 <= y2 else (y2, y1)
        return cls(x_min, y_min, x_max, y_max)


class MapCoord(NamedTuple):
    x: int
    y: int

    def __add__(self, other: tuple):
        return MapCoord(self.x + other[0], self.y + other[1])

    def __sub__(self, other: tuple):
        return MapCoord(self.x - other[0], self.y - other[1])

    def __mul__(self, other) -> MapCoord:
        if isinstance(other, int):
            return MapCoord(self.x * other, self.y * other)
        if isinstance(other, tuple):
            return MapCoord(self.x * other[0], self.y * other[1])
        raise NotImplementedError

    def encode(self) -> tuple[int, int]:
        return self.x, self.y


class MapRegion(object):
    def __init__(
        self,
        coord: MapCoord,
        image: Optional[Image.Image],
        # is_new: Optional[bool] = None,
    ):
        """
        Creates a self-contained map tile description
        :param coord: Map coordinate of the tile
        :param image: Bitmap/raster image of the tile
        """
        self.coord: MapCoord = coord
        self.image: Image.Image = image

    def __bool__(self):
        return self.image is not None

    def __str__(self):
        if self.image is None:
            return "void"
        return str(self.coord)

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self):
        return self.image.height

    @property
    def is_void(self):
        return self.image is None


def get_utc_timestamp():
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class MapStats:
    name: str
    regions: int
    voids: int
    timestamp: datetime = field(
        repr=False, compare=False, default_factory=get_utc_timestamp
    )
