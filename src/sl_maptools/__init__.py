# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import io
import math
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
    Iterator,
    NamedTuple,
    Optional,
    Protocol,
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

    def intersection(self, other: AreaBounds) -> Union[AreaBounds, None]:
        oth_x1, oth_y1, oth_x2, oth_y2 = other
        my = set(range(self.x_westmost, self.x_eastmost + 1))
        their = set(range(oth_x1, oth_x2 + 1))
        inter = my.intersection(their)
        if not inter:
            return None
        new_x1 = min(inter)
        new_x2 = max(inter)
        my = set(range(self.y_southmost, self.y_northmost + 1))
        their = set(range(oth_y1, oth_y2 + 1))
        inter = my.intersection(their)
        if not inter:
            return None
        new_y1 = min(inter)
        new_y2 = max(inter)
        return AreaBounds(new_x1, new_y1, new_x2, new_y2)

    def __and__(self, other: AreaBounds) -> Union[AreaBounds, None]:
        return self.intersection(other)

    def to_slgi(self) -> str:
        rslt = [str(self.x_westmost)]
        if self.x_eastmost != self.x_westmost:
            rslt.append(f"-{self.x_eastmost}")
        rslt.append(f"/{self.y_southmost}")
        if self.y_northmost != self.y_southmost:
            rslt.append(f"-{self.y_northmost}")
        return "".join(rslt)

    @classmethod
    def from_corners(cls, corner1: tuple[int, int], corner2: tuple[int, int]):
        x1, y1 = corner1
        x2, y2 = corner2
        x_min, x_max = (x1, x2) if x1 <= x2 else (x2, x1)
        y_min, y_max = (y1, y2) if y1 <= y2 else (y2, y1)
        return cls(x_min, y_min, x_max, y_max)

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


class AreaBoundsSet(Iterable):
    def __init__(self, areas: Union[AreaBounds, Iterable[AreaBounds]] = None):
        if areas is None:
            self.areas = frozenset()
        else:
            self.areas = frozenset([areas] if isinstance(areas, AreaBounds) else areas)

    def __contains__(self, item: CoordType):
        return any(item in area for area in self.areas)

    def __iter__(self) -> Iterator[AreaBounds]:
        return iter(self.areas)

    def __eq__(self, other: AreaBoundsSet):
        return self.areas == other.areas

    def to_coords(self) -> set[CoordType]:
        return {(x, y) for area in self.areas for x, y in area.xy_iterator()}

    def xy_iterator(self) -> Generator[CoordType, None, None]:
        _seen = set()
        xy: CoordType
        for area in self.areas:
            for xy in area.xy_iterator():
                if xy not in _seen:
                    _seen.add(xy)
                    yield xy

    def bounding_box(self) -> AreaBounds:
        x_min = y_min = math.inf
        x_max = y_max = -math.inf
        for area in self.areas:
            x1, y1, x2, y2 = area
            x_min = min(x_min, x1)
            y_min = min(y_min, y1)
            x_max = max(x_max, x2)
            y_max = max(y_max, y2)
        return AreaBounds(x_min, y_min, x_max, y_max)


class AreaDescriptor:
    def __init__(
        self,
        includes: Union[AreaBounds, Iterable[AreaBounds]],
        *,
        excludes: Union[AreaBounds, Iterable[AreaBounds]] = None,
        description: str = None
    ):
        self.includes = AreaBoundsSet(includes)
        self.excludes = AreaBoundsSet(excludes)
        self.description = description
        self._bbox: Optional[AreaBounds] = None

    def __contains__(self, item: CoordType):
        return (item in self.includes) and not (item in self.excludes)

    def __eq__(self, other: AreaDescriptor):
        return self.includes == other.includes and self.excludes == other.excludes and self.description == other.description

    @property
    def bounding_box(self) -> AreaBounds:
        if self._bbox is None:
            self._bbox = self.includes.bounding_box()
        return self._bbox

    @property
    def x_westmost(self):
        return self.bounding_box.x_westmost

    @property
    def x_eastmost(self):
        return self.bounding_box.x_eastmost

    @property
    def y_southmost(self):
        return self.bounding_box.y_southmost

    @property
    def y_northmost(self):
        return self.bounding_box.y_northmost

    def to_coords(self) -> set[CoordType]:
        return self.includes.to_coords() - self.excludes.to_coords()

    def xy_iterator(self, with_exclusions: bool = True) -> Generator[CoordType, None, None]:
        if with_exclusions:
            yield from (xy for xy in self.includes.xy_iterator() if xy not in self.excludes)
        else:
            yield from (xy for xy in self.includes.xy_iterator())

    def intersect_coords(self, other: AreaDescriptor) -> set[CoordType]:
        my_coords = self.to_coords()
        theirs = other.includes.to_coords() - other.excludes.to_coords()
        return my_coords - theirs


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


class Settable(Protocol):
    def set(self): ...
    def is_set(self) -> bool: ...


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
