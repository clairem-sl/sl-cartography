# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from enum import IntEnum
from typing import Callable, Generator, Self

from PIL import ImageDraw

from roadmapper_v3.draw import (
    Point,
    dash_pattern,
    dotgap_pattern,
    drawarc,
    drawarrow,
    drawline_patterned,
    drawline_solid,
    rails_pattern,
)
from sl_maptools.knowns import KNOWN_AREAS


class Continent:
    DrawCallback: Callable[[Self, str, Route | None, ImageDraw.ImageDraw, Point], None] = None

    def __init__(self, name: str):
        if name not in KNOWN_AREAS:
            raise KeyError()
        self.name = name
        self.bounds = KNOWN_AREAS[name]
        self.west_t, self.south_t, self.east_t, self.north_t = self.bounds

        self.westmost: float = 256.0 * self.west_t
        self.eastmost: float = 256.0 * (self.east_t + 1)
        self.southmost: float = 256.0 * self.south_t
        self.northmost: float = 256.0 * (self.north_t + 1)

        self.routes: dict[str, Route] = {}

    def __repr__(self):
        routes = [str(route) for route in self.routes.values()]
        return f"Continent({self.name}):{routes}"

    def __contains__(self, item):
        if isinstance(item, Route):
            item = item.name
        return item in self.routes

    def __getitem__(self, item: str) -> Route:
        return self.routes.get(item)

    def __setitem__(self, key: str, value: Route):
        if key != value.name:
            raise ValueError()
        self.add_route(value)

    @property
    def sw_corner(self) -> Point:
        return Point(self.westmost, self.southmost)

    @property
    def canvas_height(self) -> int:
        return round(self.northmost - self.southmost)

    @property
    def canvas_width(self) -> int:
        return round(self.eastmost - self.westmost)

    @property
    def canvas_dim(self) -> tuple[int, int]:
        return self.canvas_width, self.canvas_height

    def contains_geo(self, point: Point) -> bool:
        return self.westmost <= point.x <= self.eastmost and self.southmost <= point.y <= self.northmost

    def add_route(self, route: Route):
        if route.name in self.routes:
            raise ValueError()
        self.routes[route.name] = route

    def draw_outline(self, draw: ImageDraw.ImageDraw):
        cb = self.__class__.DrawCallback
        for route in self.routes.values():
            if cb is not None:
                cb(self, "outline", route, draw, self.sw_corner)
            route.draw_outline(draw, self.sw_corner)
        if cb is not None:
            cb(self, "outline", None, draw, self.sw_corner)

    def draw_actual(self, draw: ImageDraw.ImageDraw):
        cb = self.__class__.DrawCallback
        for route in self.routes.values():
            if cb is not None:
                cb(self, "actual", route, draw, self.sw_corner)
            route.draw_actual(draw, self.sw_corner)
        if cb is not None:
            cb(self, "actual", None, draw, self.sw_corner)

    def draw(self, draw: ImageDraw.ImageDraw):
        self.draw_outline(draw)
        self.draw_actual(draw)


class Route:
    __slots__ = ("name", "color", "segments", "segments_as_set")
    ColorCycler: Generator[tuple[int, int, int], None, None] = None
    DrawCallback: Callable[[Self, str, Segment | None, ImageDraw.ImageDraw, tuple[int, int, int], Point], None] = None

    def __init__(self, name: str, color: tuple[int, int, int] = None):
        self.name = name
        self.color = color
        self.segments: list[Segment] = []
        self.segments_as_set: set[tuple[tuple[int, int], ...]] = set()

    def __str__(self):
        return f"Route({self.name}):{len(self.segments)}segs"

    def __contains__(self, item: Segment):
        if not isinstance(item, Segment):
            raise ValueError()
        return item.as_inttuple() in self.segments_as_set

    def add_segment(self, seg: Segment, raises: bool = True):
        seg_inttuple = seg.as_inttuple()
        if seg_inttuple in self.segments_as_set:
            if raises:
                raise ValueError("Double Segments Detected!")
            return
        self.segments.append(seg)
        self.segments_as_set.add(seg_inttuple)

    def draw_outline(self, draw: ImageDraw.ImageDraw, southwest: Point):
        cb = self.__class__.DrawCallback
        for seg in self.segments:
            if cb is not None:
                cb(self, "outline", seg, draw, (0, 0, 0), southwest)
            seg.draw_outline(draw, southwest)
        if cb is not None:
            cb(self, "outline", None, draw, (0, 0, 0), southwest)

    def draw_actual(self, draw: ImageDraw.ImageDraw, southwest: Point):
        color = self.color
        if color is None:
            if self.__class__.ColorCycler is not None:
                color = next(self.__class__.ColorCycler)
        cb = self.__class__.DrawCallback
        for seg in self.segments:
            if cb is not None:
                cb(self, "actual", seg, draw, color, southwest)
            seg.draw_actual(draw, color, southwest)
        if cb is not None:
            cb(self, "actual", None, draw, color, southwest)


class SegmentMode(IntEnum):
    SOLID = 1
    DASHED = 2
    RAILS = 3
    ARC = 4
    ARROW2 = 5  # Put this first so ARROW2 becomes the 'canonical' name for value 5
    ARROW = 5
    ARROW1 = 6


class Segment:
    __slots__ = ("mode", "geopoints", "geopoints_intset", "desc", "width")
    OutlineWidth = 35
    ActualWidth = 25

    def __init__(self, mode: SegmentMode = SegmentMode.SOLID, desc: str = None, width: int = None):
        self.mode: SegmentMode = mode
        self.geopoints: list[Point] = []
        self.geopoints_intset: set[tuple[int, int]] = set()
        self.desc = desc
        self.width: int | None = width

    def as_inttuple(self) -> tuple[tuple[int, int], ...]:
        return tuple(p.rounded() for p in self.geopoints)

    def add_point(self, p: Point):
        if p.rounded() in self.geopoints_intset:
            return
        x, y = p
        self.geopoints.append(Point(round(x, 3), round(y, 3)))
        self.geopoints_intset.add(p.rounded())

    def draw_outline(
        self, draw: ImageDraw.ImageDraw, southwest: Point, extend_by: float = 4.0, extend_by_deg: float = 2.0
    ):
        if not self.geopoints:
            return
        # noinspection PyUnresolvedReferences
        cwidth, cheight = draw.im.size
        if self.width is None:
            width = self.__class__.OutlineWidth
        else:
            width = round(self.width * 1.4)
        sw_x, sw_y = southwest
        canv_points = [Point(p.x - sw_x, cheight - (p.y - sw_y)) for p in self.geopoints]
        if self.mode == SegmentMode.SOLID or self.mode == SegmentMode.RAILS:
            drawline_solid(draw, canv_points, width, (0, 0, 0), extend_by=extend_by)
        elif self.mode == SegmentMode.DASHED:
            pattern = dash_pattern((0, 0, 0))
            drawline_patterned(draw, pattern, canv_points, width, extend_by=extend_by)
        elif self.mode == SegmentMode.ARC:
            drawarc(draw, canv_points, width, (0, 0, 0), extend_by_deg=extend_by_deg)
        elif self.mode == SegmentMode.ARROW or self.mode == SegmentMode.ARROW2:
            pattern = dotgap_pattern((0, 0, 0))
            drawarrow(draw, canv_points, width, pattern, (0, 0, 0), extend_by=extend_by)
        elif self.mode == SegmentMode.ARROW1:
            pattern = dotgap_pattern((0, 0, 0))
            drawarrow(draw, canv_points, width, pattern, (0, 0, 0), both=False, extend_by=extend_by)
        else:
            raise NotImplementedError(f"Unkown mode: {self.mode!r}")

    def draw_actual(self, draw: ImageDraw.ImageDraw, color: tuple[int, int, int], southwest: Point):
        if not self.geopoints:
            return
        # noinspection PyUnresolvedReferences
        cwidth, cheight = draw.im.size
        if self.width is None:
            width = self.__class__.ActualWidth
        else:
            width = self.width
        sw_x, sw_y = southwest
        canv_points = [Point(p.x - sw_x, cheight - (p.y - sw_y)) for p in self.geopoints]
        if self.mode == SegmentMode.SOLID:
            drawline_solid(draw, canv_points, width, color)
        elif self.mode == SegmentMode.RAILS:
            pattern = rails_pattern(color)
            drawline_patterned(draw, pattern, canv_points, width)
        elif self.mode == SegmentMode.DASHED:
            pattern = dash_pattern(color)
            drawline_patterned(draw, pattern, canv_points, width)
        elif self.mode == SegmentMode.ARC:
            drawarc(draw, canv_points, width, color)
        elif self.mode == SegmentMode.ARROW or self.mode == SegmentMode.ARROW2:
            pattern = dotgap_pattern(color)
            drawarrow(draw, canv_points, width, pattern, color)
        elif self.mode == SegmentMode.ARROW1:
            pattern = dotgap_pattern(color)
            drawarrow(draw, canv_points, width, pattern, color, both=False)
        else:
            raise NotImplementedError(f"Unkown mode: {self.mode!r}")


def merge_all_routes(data1: dict[str, Continent], data2: dict[str, Continent]) -> dict[str, Continent]:
    merged: dict[str, Continent] = {}
    for conti_name, conti_data in data1.items():
        merged[conti_name] = (continent := Continent(conti_name))
        for route_name, route_data in conti_data.routes.items():
            continent.add_route((route := Route(route_name)))
            route.color = route_data.color
            for seg in route_data.segments:
                new_seg = Segment(mode=seg.mode, desc=seg.desc)
                for p in seg.geopoints:
                    new_seg.add_point(p)
                route.add_segment(seg)
    for conti_name, conti_data in data2.items():
        continent = merged.setdefault(conti_name, Continent(conti_name))
        for route_name, route_data in conti_data.routes.items():
            route = continent.routes.setdefault(route_name, Route(route_name))
            route.color = route_data.color
            for seg in route_data.segments:
                new_seg = Segment(mode=seg.mode, desc=seg.desc)
                for p in seg.geopoints:
                    new_seg.add_point(p)
                route.add_segment(seg, raises=False)
    return merged
