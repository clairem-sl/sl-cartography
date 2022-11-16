# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple, Optional

from PIL import Image


class MapBounds(NamedTuple):
    x_leftmost: int
    y_bottommost: int
    x_rightmost: int
    y_topmost: int

    def __contains__(self, item: MapCoord) -> bool:
        assert isinstance(item, MapCoord)
        x, y = item
        return (self.x_leftmost <= x <= self.x_rightmost) and (
            self.y_bottommost <= y <= self.y_topmost
        )


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


class MapTile(object):
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
