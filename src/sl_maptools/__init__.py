# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import math
import re
from collections.abc import Generator, Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple, NotRequired, Protocol, TypedDict

if TYPE_CHECKING:
    from datetime import datetime

    from PIL import Image

CoordType = tuple[int, int]
ColorType = (
    int | tuple[int] | tuple[int, int] | tuple[int, int, int] | tuple[int, int, int, int] | str | float | tuple[float]
)


class IntRange(NamedTuple):
    """Represents a range of integer, used for limits"""

    min_: int
    max_: int


COORD_RANGE: Final[IntRange] = IntRange(0, 2100)
"""Minimum and maximum coordinates, inclusive"""

RE_MAPFILE: Final[re.Pattern] = re.compile(r"^(?P<x>\d+)-(?P<y>\d+)_(?P<ts>\d{6}-\d{4}).jpe?g")
RE_SLGI_NOTATION: Final[re.Pattern] = re.compile(
    r"""
    ^\(?             # Possible open parenthesis
    \s*
    (?P<x1>\d+)      # First longitude
    (?:\s*-\s*       # Optional second longitude, there must be a hyphen
        (?P<x2>\d+)
    )?  
    \s*[,/]\s*       # Long/Lat separator
    (?P<y1>\d+)      # First latitude
    (?:\s*-\s*       # Optional second latitude, there must be a hyphen
        (?P<y2>\d+)
    )?  
    \s*
    \)?              # Possible closing parenthesis
    $
    """,
    re.VERBOSE,
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
    def height(self) -> int:
        """Height of map in Units of Regions"""
        return self.y_northmost - self.y_southmost + 1

    @property
    def width(self) -> int:
        """Width of map in Units of Regions"""
        return self.x_eastmost - self.x_westmost + 1

    def y_iterator(self) -> Generator[int, None, None]:
        """Returns an iterator of the Y coordinate"""
        min_y = min(self.y_southmost, self.y_northmost)
        max_y = max(self.y_northmost, self.y_southmost)
        yield from range(min_y, max_y + 1)

    def x_iterator(self) -> Generator[int, None, None]:
        """Returns an iterator of the X coordinate"""
        min_x = min(self.x_westmost, self.x_eastmost)
        max_x = max(self.x_eastmost, self.x_westmost)
        yield from range(min_x, max_x + 1)

    def xy_iterator(self) -> Generator[CoordType, None, None]:
        """Returns an iterator of the (x, y) coordinate, with x increasing first"""
        for y in self.y_iterator():
            for x in self.x_iterator():
                yield x, y

    def intersection(self, other: AreaBounds) -> AreaBounds | None:
        """Returns an AreaBounds containing intersecting coordinates, or None if no intersection"""
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

    def __and__(self, other: AreaBounds) -> AreaBounds | None:
        return self.intersection(other)

    def to_slgi(self) -> str:
        """Returns area coordinates in SLGI notation"""
        rslt = [str(self.x_westmost)]
        if self.x_eastmost != self.x_westmost:
            rslt.append(f"-{self.x_eastmost}")
        rslt.append(f"/{self.y_southmost}")
        if self.y_northmost != self.y_southmost:
            rslt.append(f"-{self.y_northmost}")
        return "".join(rslt)

    @classmethod
    def from_corners(cls, corner1: tuple[int, int], corner2: tuple[int, int]) -> AreaBounds:
        """Returns an AreaBound provided 2 opposing corners of the area"""
        x1, y1 = corner1
        x2, y2 = corner2
        x_min, x_max = (x1, x2) if x1 <= x2 else (x2, x1)
        y_min, y_max = (y1, y2) if y1 <= y2 else (y2, y1)
        return cls(x_min, y_min, x_max, y_max)

    @classmethod
    def from_coordset(cls, coords: Iterable[CoordType]) -> AreaBounds:
        """Returns an AreaBound that exactly contains all coordinates"""
        x_min, y_min = tuple(map(min, *coords))
        x_max, y_max = tuple(map(max, *coords))
        return cls(x_min, y_min, x_max, y_max)

    @classmethod
    def from_slgi(cls, notation: str) -> AreaBounds:
        """Returns an AreaBound from parsing SLGI notation"""
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
    """A wrapper around a frozenset of AreaBounds"""

    def __init__(self, areas: AreaBounds | Iterable[AreaBounds] = None):
        """
        :param areas: One or more AreaBounds to contain
        """
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
        """Returns a set of coordinates contained in all AreaBounds in the set"""
        return {(x, y) for area in self.areas for x, y in area.xy_iterator()}

    def xy_iterator(self) -> Generator[CoordType, None, None]:
        """
        Returns an iterator of the (x, y) coordinate, x increasing first, running over all AreaBounds in the set.
        The coordinates are guaranteed to not be duplicated.
        """
        _seen = set()
        xy: CoordType
        for area in self.areas:
            for xy in area.xy_iterator():
                if xy not in _seen:
                    _seen.add(xy)
                    yield xy

    def bounding_box(self) -> AreaBounds:
        """Returns an AreaBounds that exactly contains all areas in the set"""
        x_min = y_min = math.inf
        x_max = y_max = -math.inf
        for area in self.areas:
            x1, y1, x2, y2 = area
            x_min = min(x_min, x1)
            y_min = min(y_min, y1)
            x_max = max(x_max, x2)
            y_max = max(y_max, y2)
        return AreaBounds(x_min, y_min, x_max, y_max)


AreaDescriptorPragma = TypedDict(
    "AreaDescriptorPragma",
    {
        "automatic": NotRequired[bool],
        "validate": NotRequired[bool],
        "target-dir": NotRequired[bool],
    },
)


DEFAULT_ADPRAGMA: AreaDescriptorPragma = {
    "automatic": True,
    "validate": True,
}


class AreaDescriptor:
    """Describes an area for purposes of mapping"""

    __slots__ = (
        "includes",
        "excludes",
        "name",
        "description",
        "pragma",
        "_bbox",
    )

    def __init__(
        self,
        includes: AreaBounds | Iterable[AreaBounds],
        *,
        excludes: AreaBounds | Iterable[AreaBounds] = None,
        name: str | None = None,
        description: str | None = None,
        pragma: AreaDescriptorPragma = None,
    ):
        """
        :param includes: One or more AreaBound objects that describe the area
        :param excludes: One or more AreaBound objects that need to be excluded
        :param name: Name of the area
        :param description: Description of the area
        :param pragma: Metadata of the area
        """
        self.includes = AreaBoundsSet(includes)
        self.excludes = AreaBoundsSet(excludes)
        self.name = name
        self.description = description
        self.pragma = DEFAULT_ADPRAGMA | (pragma or {})
        self._bbox: AreaBounds | None = None

    def __contains__(self, item: CoordType):
        return (item in self.includes) and item not in self.excludes

    def __eq__(self, other: AreaDescriptor):
        return self.includes == other.includes and self.excludes == other.excludes

    @property
    def automatic(self) -> bool:
        """Whether the area will automatically be drawn if not specified explicitly"""
        return self.pragma["automatic"]

    @property
    def validate(self) -> bool:
        """Whether the area will obey coordinate validation"""
        return self.pragma["validate"]

    @property
    def target_dir(self) -> bool | None:
        """Preferred target directory, if any"""
        return self.pragma.get("target-dir")

    @property
    def bounding_box(self) -> AreaBounds:
        """Returns an AreaBounds that exactly contains all AreaBounds of the area"""
        if self._bbox is None:
            self._bbox = self.includes.bounding_box()
        return self._bbox

    @property
    def x_westmost(self) -> int:
        """Returns westmost X geo-coordinate of the area"""
        return self.bounding_box.x_westmost

    @property
    def x_eastmost(self) -> int:
        """Returns eastmost X geo-coordinate of the area"""
        return self.bounding_box.x_eastmost

    @property
    def y_southmost(self) -> int:
        """Returns southmost Y geo-coordinate of the area"""
        return self.bounding_box.y_southmost

    @property
    def y_northmost(self) -> int:
        """Returns northmost Y geo-coordinate of the area"""
        return self.bounding_box.y_northmost

    def to_coords(self) -> set[CoordType]:
        """
        Returns a set of coordinates in the area excluding those not actually part of the area.
        NO VALIDATION.
        """
        return self.includes.to_coords() - self.excludes.to_coords()

    def xy_iterator(self, with_exclusions: bool = True) -> Generator[CoordType, None, None]:
        """
        Returns an iterator of (x, y) coordinates of an area.

        :param with_exclusions: If True, will not return coordinates part of the excludes
        """
        if with_exclusions:
            yield from (xy for xy in self.includes.xy_iterator() if xy not in self.excludes)
        else:
            yield from (xy for xy in self.includes.xy_iterator())

    def intersect_coords(self, other: AreaDescriptor) -> set[CoordType]:
        """Returns a set of coordinates from intersection with another AreaDescriptor"""
        my_coords = self.to_coords()
        theirs = other.includes.to_coords() - other.excludes.to_coords()
        return my_coords - theirs


class MapCoord(NamedTuple):
    """Representation of Geo Coordinates. Behaves similarly to tuple[int, int]"""

    x: int
    y: int

    def __add__(self, other: tuple):
        return MapCoord(self.x + other[0], self.y + other[1])

    def __sub__(self, other: tuple):
        return MapCoord(self.x - other[0], self.y - other[1])

    def __mul__(self, other: int | tuple) -> MapCoord:
        if isinstance(other, int):
            return MapCoord(self.x * other, self.y * other)
        if isinstance(other, tuple):
            return MapCoord(self.x * other[0], self.y * other[1])
        raise NotImplementedError

    def encode(self) -> tuple[int, int]:
        """Returns a 'pure' tuple[int, int]"""
        return self.x, self.y


class MapRegion:
    """
    A Map Tile (image of a region) with its global geo-coordinates
    """

    def __init__(
        self,
        coord: MapCoord,
        image: Image.Image | None,
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
        """Width of the map tile"""
        return self.image.width

    @property
    def height(self) -> int:
        """Height of the map tile"""
        return self.image.height

    @property
    def is_void(self) -> bool:
        """True if map tile is a void (no image)"""
        return self.image is None


class RegionsDBRecord(TypedDict):
    """
    Version 1 of RegionsDB record
    """

    first_seen: str
    last_seen: str
    last_check: str
    current_name: str
    name_history: dict[str, list[str]]
    sources: set[str]


class RegionsDBRecord3(TypedDict):
    """
    Version 3 of RegionsDB record
    """

    first_seen: datetime
    last_seen: datetime | None
    last_check: datetime | None
    current_name: str
    name_history3: dict[str, list[tuple[datetime, datetime]]]
    sources: set[str]


class SupportsSet(Protocol):  # noqa: D101
    def set(self) -> None:  # noqa: D102
        ...

    def is_set(self) -> bool:  # noqa: D102
        ...


def inventorize_maps_latest(mapdir: Path | str) -> dict[CoordType, Path]:
    """Makes a dict of all available map tiles, by region coords"""
    mapdir = Path(mapdir)
    rslt: dict[CoordType, Path] = {}
    for fp in sorted(mapdir.glob("*.jp*"), reverse=True):
        if (m := RE_MAPFILE.match(fp.name)) is None:
            continue
        coord = int(m.group("x")), int(m.group("y"))
        if coord not in rslt:
            rslt[coord] = fp
    return rslt


def inventorize_maps_all(mapdir: Path | str) -> dict[CoordType, list[Path]]:
    """
    Returns a dict (by coordinate) of maptile files in mapdir, sorted ascending by filename.
    (So if filename has timestamp, the latest will be the last)

    :param mapdir: Directory containing the maptile files
    """
    mapdir: Path = Path(mapdir)
    rslt: dict[CoordType, list[Path]] = {}
    for fp in sorted(mapdir.glob("*.jp*")):
        if (m := RE_MAPFILE.match(fp.name)) is None:
            continue
        coord = int(m.group("x")), int(m.group("y"))
        rslt.setdefault(coord, []).append(fp)
    return rslt
