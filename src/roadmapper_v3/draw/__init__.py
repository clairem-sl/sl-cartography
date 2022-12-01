# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import math
from itertools import cycle, pairwise
from typing import NamedTuple

from PIL import ImageDraw


class Point(NamedTuple):
    x: float
    y: float

    def rounded(self) -> tuple[int, int]:
        return round(self.x), round(self.y)

    def is_close(self, other: Point) -> bool:
        return math.isclose(self.x, other.x) and math.isclose(self.y, other.y)

    def __mul__(self, multiplier: float):
        return Point(self.x * multiplier, self.y * multiplier)


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


def extend_points(points: list[Point], extend_by: float):
    new_p0 = extend_by_t(points[1], points[0], extend_by)
    new_pz = extend_by_t(points[-2], points[-1], extend_by)
    return [new_p0, *points[1:-1], new_pz]


class ParametricLine:
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


class Pattern(NamedTuple):
    length: float
    color: tuple[int, int, int] | None


def drawline_patterned(
    drawer: ImageDraw.ImageDraw,
    patterns: dict[str, Pattern],
    points: list[Point],
    width: int = 10,
    min_len: float = 0.01,
    extend_by: float = None,
):
    segments: list[tuple[Point, Point]] = []

    pattern_cycle = cycle(patterns.items())
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
            drawpoints = extend_points(drawpoints, extend_by)
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
def dash_pattern(color: tuple[int, int, int], dash_len: int = 50, blank_len: int = 30):
    return {
        "blank": Pattern(blank_len, None),
        "dash": Pattern(dash_len, color),
    }


def rails_pattern(color: tuple[int, int, int], dash_len: int = 60, pip_len: int = 15, gap_len: int = 10):
    return {
        "dash": Pattern(dash_len, color),
        "pip1": Pattern(pip_len, (0, 0, 0)),
        "gapp": Pattern(gap_len, color),
        "pip2": Pattern(pip_len, (0, 0, 0)),
    }


def drawline_solid(
    drawer: ImageDraw.ImageDraw, points: list[Point], width: int, color: tuple[int, int, int], extend_by: float = None
):
    if extend_by:
        points = extend_points(points, extend_by)
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
