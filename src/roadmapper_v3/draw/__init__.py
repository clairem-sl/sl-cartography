# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import math
from itertools import cycle, pairwise
from typing import Generator, NamedTuple

from PIL import ImageDraw

from roadmapper_v3.model import Point, Route, Segment, SegmentMode


def extend_by_t(p1: Point, p2: Point, t: float) -> Point:
    """Extend p1->p2 vector by at least t pixels beyond p2."""
    if p1.is_close(p2):
        raise ValueError("p1 and p2 are duplicates!")
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    leng = math.sqrt(dx**2 + dy**2)
    x3 = x1 + (t / leng + 1) * dx
    y3 = y1 + (t / leng + 1) * dy
    return Point(x3, y3)


def extend_ends(points: list[Point], extend_by: float):
    new_p0 = extend_by_t(points[1], points[0], extend_by)
    new_pz = extend_by_t(points[-2], points[-1], extend_by)
    return [new_p0, *points[1:-1], new_pz]


class ParametricLine:
    __slots__ = ("p1", "p2")

    def __init__(self, p1: Point, p2: Point):
        self.p1 = p1
        self.p2 = p2

    @property
    def displacement(self) -> Point:
        x1, y1 = self.p1
        x2, y2 = self.p2
        return Point((x2 - x1), (y2 - y1))

    @property
    def length(self):
        dx, dy = self.displacement
        return math.sqrt(dx**2 + dy**2)

    def move_start_by(self, t: float) -> Point:
        leng = self.length
        dx, dy = self.displacement
        new_x = self.p1.x + (t / leng) * dx
        new_y = self.p1.y + (t / leng) * dy
        self.p1 = Point(new_x, new_y)
        return self.p1


class PhaseDesc(NamedTuple):
    length: float
    color: tuple[int, int, int] | None


class LinePattern:
    __slots__ = ("color", "phases")

    def __init__(self, color: tuple[int, int, int], *phases: tuple[str, float, bool | None | tuple[int, int, int]]):
        self.color = color
        self.phases: dict[str, PhaseDesc] = {}
        for phase_name, phase_len, phase_clr in phases:
            clr = None
            if phase_clr is True:
                clr = self.color
            elif phase_clr is None or phase_clr is False:
                clr = None
            elif isinstance(phase_clr, tuple) and len(phase_clr) == 3:
                clr = phase_clr
            self.phases[phase_name] = PhaseDesc(phase_len, clr)


def drawline_patterned(
    drawer: ImageDraw.ImageDraw,
    pattern: LinePattern,
    points: list[Point],
    width: int = 10,
    min_len: float = 0.01,
    extend_by: float = None,
):
    segments: list[tuple[Point, Point]] = []

    pattern_cycle = cycle(pattern.phases.items())
    point_pairs = pairwise(points)

    phase, (phase_len, phase_clr) = next(pattern_cycle)
    pline: ParametricLine | None = None
    p1 = p2 = Point(math.nan, math.nan)

    def _do_draw():
        if phase_clr is None:
            segments.clear()
            return
        drawpoints: list[Point] = []
        prev_p2 = segments[0][0]
        _p2 = None
        for _p1, _p2 in segments:
            assert _p1.is_close(prev_p2)
            drawpoints.append(_p1)
            prev_p2 = _p2
        drawpoints.append(_p2)
        if extend_by:
            drawpoints = extend_ends(drawpoints, extend_by)
        drawpoints_int = [p.rounded() for p in drawpoints]
        drawer.line(drawpoints_int, fill=phase_clr, width=width, joint="curve")
        segments.clear()

    while True:
        if pline is None:
            try:
                p1, p2 = next(point_pairs)
                pline = ParametricLine(p1, p2)
            except StopIteration:
                break
        pline_len = pline.length

        if pline_len > phase_len:
            p3 = pline.move_start_by(phase_len)
            segments.append((p1, p3))
            _do_draw()
            p1 = p3
            phase, (phase_len, phase_clr) = next(pattern_cycle)
            continue

        segments.append((p1, p2))
        phase_len -= pline_len
        pline = None
        if abs(phase_len) < min_len:
            _do_draw()
            phase, (phase_len, phase_clr) = next(pattern_cycle)

    if segments:
        _do_draw()


# def dash_pattern(color: tuple[int, int, int], dash_len: int = 60, blank_len: int = 40):
def dash_pattern(color: tuple[int, int, int], dash_len: int = 50, blank_len: int = 30) -> LinePattern:
    return LinePattern(
        color,
        ("blank", blank_len, None),
        ("dash", dash_len, True),
    )


def rails_pattern(color: tuple[int, int, int], dash_len: int = 60, pip_len: int = 15, gap_len: int = 10) -> LinePattern:
    return LinePattern(
        color,
        ("dash", dash_len, True),
        ("pip1", pip_len, (0, 0, 0)),
        ("gapp", gap_len, True),
        ("pip2", pip_len, (0, 0, 0)),
    )


def dotgap_pattern(color: tuple[int, int, int], gap_len: int = 40) -> LinePattern:
    return LinePattern(
        color,
        ("dot", 20, True),
        ("gap", gap_len, False),
    )


def drawline_solid(
    drawer: ImageDraw.ImageDraw, points: list[Point], width: int, color: tuple[int, int, int], extend_by: float = None
):
    if extend_by:
        points = extend_ends(points, extend_by)
    int_points = [p.rounded() for p in points]
    drawer.line(int_points, width=width, fill=color, joint="curve")


def drawarc(
    drawer: ImageDraw.ImageDraw,
    points: list[Point],
    width: int,
    color: tuple[int, int, int],
    extend_by_deg: float = 0.0,
):
    def fit_circle_cartes(
        x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ) -> tuple[Point, float, bool] | None:
        slope_a: float = (x2 - x1) / (y1 - y2)
        slope_b: float = (x3 - x2) / (y2 - y3)
        if math.isclose(slope_a, slope_b):
            return None
        if math.isclose(y1, y2):
            x = (x1 + x2) / 2
            y = slope_b * x + (((y2 + y3) / 2) - slope_b * ((x2 + x3) / 2))
        elif math.isclose(y2, y3):
            x = (x2 + x3) / 2
            y = slope_a * x + (((y1 + y2) / 2) - slope_a * ((x1 + x2) / 2))
        else:
            u = ((y1 + y2) / 2) - slope_a * ((x1 + x2) / 2)
            x = (((y2 + y3) / 2 - slope_b * (x2 + x3) / 2) - u) / (slope_a - slope_b)
            y = slope_a * x + u
        r = math.sqrt((x1 - x) ** 2 + (y1 - y) ** 2)
        ccw = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) >= 0
        return Point(x, y), r, ccw

    if len(points) != 3:
        raise ValueError("'ARC' segments need EXACTLY 3 (three) points, no more, no less!")

    cx1, cy1 = points[0]
    cx2, cy2 = points[1]
    cx3, cy3 = points[2]

    # noinspection PyUnresolvedReferences
    _, cheight = drawer.im.size

    # Operate in Cartesian mode
    gy1 = cheight - cy1
    gy2 = cheight - cy2
    gy3 = cheight - cy3
    circle: tuple[Point, float, bool]
    if (circle := fit_circle_cartes(cx1, gy1, cx2, gy2, cx3, gy3)) is None:
        return None
    center, radius, countercw = circle
    ang1 = math.degrees(math.atan2(gy1 - center.y, cx1 - center.x))
    ang2 = math.degrees(math.atan2(gy3 - center.y, cx3 - center.x))
    # End Cartesian mode, back to Canvas mode

    if not countercw:
        ang1, ang2 = ang2, ang1
    ang1 = 360.0 - ang1 - extend_by_deg
    ang2 = 360.0 - ang2 + extend_by_deg

    bx1, bx2 = sorted([(center.x - radius), (center.x + radius)])
    by1, by2 = sorted([(cheight - (center.y - radius)), (cheight - (center.y + radius))])
    bbox = (bx1, by1, bx2, by2)
    drawer.arc(bbox, ang1, ang2, fill=color, width=width)


def get_arrow_endpoints(p1: Point, p2: Point, theta_deg: float = 15.0, arrow_len: float = 80.0) -> tuple[Point, Point]:
    """
         p3
        /
    p2 <---- p1
        \
         p4

    Angle p1-p2-p3 == angle p1-p2-p4 == "theta"
    """
    # Source: https://math.stackexchange.com/a/1314050/132442
    x1, y1 = p1
    x2, y2 = p2
    l1 = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    l2 = arrow_len
    l_ratio = l2 / l1
    theta_rad = theta_deg / 180 * math.pi
    cos_theta = math.cos(theta_rad)
    sin_theta = math.sin(theta_rad)
    x3 = x2 + l_ratio * ((x1 - x2) * cos_theta + (y1 - y2) * sin_theta)
    y3 = y2 + l_ratio * ((y1 - y2) * cos_theta - (x1 - x2) * sin_theta)
    x4 = x2 + l_ratio * ((x1 - x2) * cos_theta - (y1 - y2) * sin_theta)
    y4 = y2 + l_ratio * ((y1 - y2) * cos_theta + (x1 - x2) * sin_theta)
    return Point(x3, y3), Point(x4, y4)


def drawarrow(
    drawer: ImageDraw.ImageDraw,
    points: list[Point],
    width: int,
    pattern: LinePattern,
    both: bool = True,
    extend_by: float = None,
):
    """
    Draw an arrow with patterned line.

    :param drawer: ImageDraw.ImageDraw to draw with
    :param points: List of canvas points
    :param width: Width of line and arrow head arms
    :param pattern: Pattern of the line
    :param both: If True (default) draw arrow on both ends. If False, draw only at end
    :param extend_by: Extend the endings by this many pixels
    """
    drawline_patterned(drawer, pattern, points, width, extend_by=extend_by)

    if both:
        p1 = points[1]
        p2 = points[0]
        p3, p4 = get_arrow_endpoints(p1, p2)
        drawline_solid(drawer, [p3, p2, p4], width, pattern.color, extend_by)

    p1 = points[-2]
    p2 = points[-1]
    p3, p4 = get_arrow_endpoints(p1, p2)
    drawline_solid(drawer, [p3, p2, p4], width, pattern.color, extend_by)


class SegmentDrawer:
    __slots__ = ("route", "segment", "mode", "drawer", "geo_southwest")
    OutlineWidth = 35
    ActualWidth = 25
    ColorCycler: Generator[tuple[int, int, int], None, None] = None

    _RouteColors: dict[str, tuple[int, int, int]] = {}

    def __init__(self, route: Route, segment: Segment, drawer: ImageDraw.ImageDraw, geo_southwest: Point):
        self.route = route
        self.segment = segment
        self.mode = segment.mode
        self.drawer = drawer
        self.geo_southwest = geo_southwest

    def _route_color(self) -> tuple[int, int, int] | None:
        _route_colors = self.__class__._RouteColors
        if self.route.name not in _route_colors:
            color = self.route.color
            if color is None:
                if self.__class__.ColorCycler is not None:
                    color = next(self.__class__.ColorCycler)
            _route_colors[self.route.name] = color
        return _route_colors[self.route.name]

    def draw_outline(self, extend_by: float = 4.0, extend_by_deg: float = 2.0):
        if not self.segment.geopoints:
            return
        draw = self.drawer
        # noinspection PyUnresolvedReferences
        cwidth, cheight = draw.im.size
        if self.segment.width is None:
            width = self.__class__.OutlineWidth
        else:
            width = round(self.segment.width * 1.4)
        sw_x, sw_y = self.geo_southwest
        canv_points = [Point(p.x - sw_x, cheight - (p.y - sw_y)) for p in self.segment.geopoints]
        if self.mode == SegmentMode.SOLID or self.mode == SegmentMode.RAILS:
            drawline_solid(draw, canv_points, width, (0, 0, 0), extend_by=extend_by)
        elif self.mode == SegmentMode.DASHED:
            pattern = dash_pattern((0, 0, 0))
            drawline_patterned(draw, pattern, canv_points, width, extend_by=extend_by)
        elif self.mode == SegmentMode.ARC:
            drawarc(draw, canv_points, width, (0, 0, 0), extend_by_deg=extend_by_deg)
        elif self.mode == SegmentMode.ARROW or self.mode == SegmentMode.ARROW2:
            pattern = dotgap_pattern((0, 0, 0))
            drawarrow(draw, canv_points, width, pattern, extend_by=extend_by)
        elif self.mode == SegmentMode.ARROW1:
            pattern = dotgap_pattern((0, 0, 0))
            drawarrow(draw, canv_points, width, pattern, both=False, extend_by=extend_by)
        else:
            raise NotImplementedError(f"Don't know how to draw mode: {self.mode!r}")

    def draw_actual(self):
        if not self.segment.geopoints:
            return
        draw = self.drawer
        # noinspection PyUnresolvedReferences
        cwidth, cheight = draw.im.size
        if self.segment.width is None:
            width = self.__class__.ActualWidth
        else:
            width = self.segment.width
        sw_x, sw_y = self.geo_southwest
        canv_points = [Point(p.x - sw_x, cheight - (p.y - sw_y)) for p in self.segment.geopoints]
        color = self._route_color()
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
            drawarrow(draw, canv_points, width, pattern)
        elif self.mode == SegmentMode.ARROW1:
            pattern = dotgap_pattern(color)
            drawarrow(draw, canv_points, width, pattern, both=False)
        else:
            raise NotImplementedError(f"Don't know how to draw mode: {self.mode!r}")
