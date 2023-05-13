# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, NamedTuple, Optional, Union, TypedDict, Generator

from PIL import Image


CoordType = tuple[int, int]


RE_MAPFILE: Final[re.Pattern] = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_(?P<ts>\d{6}-\d{4}).jpe?g")


_REGION_SIZE: Final[int] = 256


class AreaBounds(NamedTuple):
    """
    Boundaries of an area, usually in terms of Map Coordinates
    """
    x_westmost: int
    y_southmost: int
    x_eastmost: int
    y_northmost: int

    def __str__(self):
        return f"({self.x_westmost},{self.y_southmost})-({self.x_eastmost},{self.y_northmost})"

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

    def y_iterator(self) -> Generator[int, None, None]:
        min_y = min(self.y_southmost, self.y_northmost)
        max_y = max(self.y_northmost, self.y_southmost)
        yield from range(min_y, max_y + 1)

    def x_iterator(self) -> Generator[int, None, None]:
        min_x = min(self.x_westmost, self.x_eastmost)
        max_x = max(self.x_eastmost, self.x_westmost)
        yield from range(min_x, max_x + 1)


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


class MapCanvas(object):
    """
    A canvas where the map will be drawn
    """
    def __init__(
        self,
        south_west: MapCoord,
        width: int,
        height: int,
        *,
        void_image: Image.Image = None,
        initial_tiles=None,
    ):
        """
        Creates a MapCanvas object.

        :param south_west: Coordinates of the region that will be in the lower-left corner
        :param width: Width of the canvas, in pixels
        :param height: Height of the canvas, in pixels
        """
        canv_w = width * _REGION_SIZE
        canv_h = height * _REGION_SIZE
        self.canvas = Image.new("RGBA", (canv_w, canv_h), color=initial_tiles)
        self.void_image = void_image
        self.south_west = south_west
        self.width = width
        self.height = height
        self._min_x = self.south_west.x
        self._max_y = self.south_west.y + self.height - 1

    def add_region(self, region: MapRegion):
        if region.is_void and self.void_image is None:
            return
        tile_x, tile_y = region.coord
        canv_x = (tile_x - self._min_x) * _REGION_SIZE
        canv_y = (self._max_y - tile_y) * _REGION_SIZE
        self.canvas.paste(region.image, (canv_x, canv_y))

    def save_to(self, dest: Union[Path | io.IOBase], image_format: str = None, optimize: bool = True):
        if isinstance(dest, io.IOBase):
            if not image_format:
                raise ValueError("image_format must be specified if dest is a stream")
        if dest.suffix == ".png" or (image_format and image_format.casefold() == "png"):
            self.canvas.save(dest, format=image_format, optimize=optimize)
        else:
            self.canvas.save(dest, format=image_format)

    @property
    def size(self):
        return self.canvas.size


def inventorize_maps_latest(mapdir: Path) -> dict[CoordType, Path]:
    rslt: dict[CoordType, Path] = {}
    for fp in sorted(mapdir.glob("*.jp*"), reverse=True):
        if (m := RE_MAPFILE.match(fp.name)) is None:
            continue
        coord = int(m.group("x")), int(m.group("y"))
        if coord not in rslt:
            rslt[coord] = fp
    return rslt


def inventorize_maps_all(mapdir: Path) -> dict[CoordType, list[Path]]:
    rslt: dict[CoordType, list[Path]] = {}
    for fp in sorted(mapdir.glob("*.jp*")):
        if (m := RE_MAPFILE.match(fp.name)) is None:
            continue
        coord = int(m.group("x")), int(m.group("y"))
        rslt.setdefault(coord, []).append(fp)
    return rslt


class RegionsDBRecord(TypedDict):
    first_seen: str
    last_seen: str
    last_check: str
    current_name: str
    name_history: dict[str, list[str]]
    sources: set[str]
