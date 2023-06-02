# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from operator import methodcaller
from pathlib import Path
from typing import (
    Callable,
    Final,
    Generator,
    Iterable,
    NamedTuple,
    Optional,
    TypedDict,
    Union,
)

from PIL import Image

CoordType = tuple[int, int]

COORD_RANGE: Final[tuple[int, int]] = (0, 2100)
"""Minimum and maximum coordinates, inclusive"""

RE_MAPFILE: Final[re.Pattern] = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_(?P<ts>\d{6}-\d{4}).jpe?g")
RE_SLGI_NOTATION: Final[re.Pattern] = re.compile(
    r"""
    ^\D*             # Possible open parenthesis
    (?P<x1>\d+)      # First longitude
    (-(?P<x2>\d+))?  # Optional second longitude
    (                  # Optional latitude
        \s*[,/]\s*       # Long/Lat separator
        (?P<y1>\d+)      # First latitude
        (-(?P<y2>\d+))?  # Optional second latitude
    )?
    """,
    re.VERBOSE
)

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

    def __repr__(self):
        return f"AreaBounds({self.x_westmost}, {self.y_southmost}, {self.x_eastmost}, {self.y_northmost})"

    def __contains__(self, item: tuple[int, int]) -> bool:
        x, y = item
        return (self.x_westmost <= x <= self.x_eastmost) and (self.y_southmost <= y <= self.y_northmost)

    @property
    def height(self):
        """Height of map in Units of Regions"""
        return self.y_northmost - self.y_southmost + 1

    @property
    def width(self):
        """Width of map in Units of Regions"""
        return self.x_eastmost - self.x_westmost + 1

    @classmethod
    def from_corners(cls, corner1: tuple[int, int], corner2: tuple[int, int]):
        x1, y1 = corner1
        x2, y2 = corner2
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

    def xy_iterator(self) -> Generator[CoordType, None, None]:
        for y in self.y_iterator():
            for x in self.x_iterator():
                yield x, y

    @classmethod
    def from_coordset(cls, coords: Iterable[CoordType]):
        x_min, y_min = tuple(map(min, *coords))
        x_max, y_max = tuple(map(max, *coords))
        return cls(x_min, y_min, x_max, y_max)

    @classmethod
    def from_slgi(cls, notation: str) -> AreaBounds:
        if (m := RE_SLGI_NOTATION.match(notation)) is None:
            raise ValueError(f"Not an SLGI notation: {notation}")
        x_min = m.group("x1")
        x_max = m.group("x2") or x_min
        y_min = m.group("y1")
        y_max = m.group("y2") or y_min
        if y_min is None:
            raise ValueError(f"Albeit valid, the notation does not describe an area: {notation}")
        return cls(int(x_min), int(y_min), int(x_max), int(y_max))


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


@dataclass(frozen=True)
class MapStats:
    name: str
    regions: int
    voids: int
    timestamp: datetime = field(repr=False, compare=False, default_factory=partial(datetime.now, tz=timezone.utc))


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


class RegionsDBRecord(TypedDict):
    first_seen: str
    last_seen: str
    last_check: str
    current_name: str
    name_history: dict[str, list[str]]
    sources: set[str]


class RegionsDBRecord3(TypedDict):
    first_seen: datetime
    last_seen: Union[datetime, None]
    last_check: Union[datetime, None]
    current_name: str
    name_history3: dict[str, list[tuple[datetime, datetime]]]
    sources: set[str]


def friendly_db_record(record: RegionsDBRecord3) -> dict:
    isofmin: Callable[[datetime], str] = methodcaller("isoformat", timespec="minutes")
    rslt = {"current_name": record["current_name"]}
    for _field in ("last_seen", "last_check", "first_seen"):
        # noinspection PyTypedDict
        rslt[_field] = isofmin(record.get(_field)).replace("T", " ")
    rslt["name_history3"] = {
        name: [(isofmin(t1), isofmin(t2)) for t1, t2 in hist]
        for name, hist in record["name_history3"].items()
    }
    rslt["sources"] = record["sources"]
    return rslt
