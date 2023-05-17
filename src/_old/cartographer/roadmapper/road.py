# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import math
from enum import IntEnum
from itertools import cycle, islice
from pathlib import Path
from typing import NamedTuple, Self, TypedDict

import msgpack
from PIL import Image, ImageDraw


class DrawMode(IntEnum):
    SOLID = 1
    DASHED = 2
    RAILS = 3
    ARC = 4


class Point(NamedTuple):
    x: float
    y: float

    def is_close(self, other: Point) -> bool:
        return math.isclose(self.x, other.x) and math.isclose(self.y, other.y)

    def rounded(self) -> tuple[int, int]:
        return round(self.x), round(self.y)


def extend_by_n(p1: Point, p2: Point, n: int) -> Point:
    """Extend by at least n pixels."""
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    if dx == dy == 0:
        raise ValueError("p1 and p2 are duplicates!")
    if abs(dx) > abs(dy):
        # Horizontally oriented
        _n = n if dx >= 0 else -n
        x3 = x2 + _n
        y3 = (x3 - x1) * dy / dx + y1
    else:
        # Vertically oriented
        _n = n if dy >= 0 else -n
        y3 = y2 + _n
        x3 = (y3 - y1) * dx / dy + x1
    return Point(x3, y3)


# pp1 = Point(1, 1)
# pp2 = Point(2, 3)
# print(extend_by_n(pp1, pp2, 2))
# print(extend_by_n(pp2, pp1, 2))


class SegmentSerialized(TypedDict):
    """A data structure serializable by MessagePack, derived from Segment"""

    __mode: int
    __color: None | tuple[int, int, int]
    __points: list[tuple[float, float]]


class _RailsDrawMode(IntEnum):
    solid = 0
    rail1 = 1
    gap = 2
    rail2 = 3


class SegmentError(ValueError):
    pass


class Segment:
    """A segment of the Road."""

    BlackWidth = 35
    ColorWidth = 25

    def __init__(self, mode: DrawMode, color: tuple[int, int, int] = None):
        self.mode: DrawMode = mode
        self.color: None | tuple[int, int, int] = color
        self.canvas_points: list[Point] = []

    def __repr__(self):
        return f"Segment(" f"{self.mode}, " f"{self.color}, " f"{self.canvas_points}" f")"

    def __eq__(self, other: Segment):
        if self.mode != other.mode:
            return False
        if self.color != other.color:
            return False
        if len(self.canvas_points) != len(other.canvas_points):
            return False
        return all(a.is_close(b) for a, b in zip(self.canvas_points, other.canvas_points))

    def __contains__(self, item: Point):
        for p in self.canvas_points:
            if p.is_close(item):
                return True
        return False

    def points_as_tuple(self) -> tuple[tuple[int, int], ...]:
        return tuple(cp.rounded() for cp in self.canvas_points)

    def add_point(self, point: Point, add_halfway: bool = False) -> None:
        if self.canvas_points and add_halfway:
            px, py = pp = self.canvas_points[-1]
            hx = (point.x - px) / 2 + px
            hy = (point.y - py) / 2 + py
            hp = Point(hx, hy)
            if not hp.is_close(pp) and not hp.is_close(point):
                self.canvas_points.append(hp)
        self.canvas_points.append(point)

    @staticmethod
    def _draw_line(
        draw: ImageDraw, points: list[Point], width: int, fill: tuple[int, int, int], extend_by: int = 0
    ) -> None:
        seen = set()
        uniques = []
        for p in points:
            if p in seen:
                continue
            seen.add(p)
            uniques.append(p)
        if len(uniques) < 2:
            return
        points = uniques
        if extend_by:
            new_p0 = extend_by_n(points[1], points[0], extend_by)
            new_pz = extend_by_n(points[-2], points[-1], extend_by)
            points = [new_p0, *points[1:-1], new_pz]
        int_points = [p.rounded() for p in points]
        draw.line(int_points, width=width, fill=fill, joint="curve")

    def _draw_dashed(
        self,
        draw: ImageDraw.ImageDraw,
        width: int,
        color: tuple[int, int, int],
        start_blank: bool = True,
        dash_len: int = 5,
        blank_len: int = 4,
        extend_by: int = 0,
    ) -> None:
        """Draw a dashed line."""
        c = -1 if (blank := start_blank) else 0
        piece_points: list[Point] = []
        blank_len -= 1
        dash_len += 1
        for point in self.canvas_points:
            c += 1
            if blank:
                if c >= blank_len:
                    c = 0
                    blank = False
                continue
            piece_points.append(point)
            if c >= dash_len:
                self._draw_line(draw, piece_points, width=width, fill=color, extend_by=extend_by)
                c = 0
                blank = True
                piece_points.clear()
        if not blank and piece_points:
            self._draw_line(draw, piece_points, width=width, fill=color, extend_by=extend_by)

    def _draw_rails(
        self,
        draw: ImageDraw.ImageDraw,
        width: int,
        color: tuple[int, int, int],
        rails_color: tuple[int, int, int] = (0, 0, 0),
        non_rails_len: int = 3,
        rails_len: int = 1,
        railgaps_len: int = 1,
    ) -> None:
        params: dict[_RailsDrawMode, tuple[int, tuple[int, int, int]]] = {
            _RailsDrawMode.solid: (non_rails_len, color),
            _RailsDrawMode.rail1: (rails_len, rails_color),
            _RailsDrawMode.gap: (railgaps_len, color),
            _RailsDrawMode.rail2: (rails_len, rails_color),
        }
        _crdm = cycle(_RailsDrawMode)
        piece_points = [self.canvas_points[0]]
        c = 0
        limit, clr = params[next(_crdm)]
        for point in islice(self.canvas_points, 1, None):
            piece_points.append(point)
            c += 1
            if c >= limit:
                self._draw_line(draw, piece_points, width=width, fill=clr)
                piece_points = [piece_points[-1]]
                c = 0
                limit, clr = params[next(_crdm)]
                continue
        if len(piece_points) >= 2:
            self._draw_line(draw, piece_points, width=width, fill=clr)

    def _draw_solid(
        self, draw: ImageDraw.ImageDraw, width: int, color: tuple[int, int, int], extend_by: int = 0
    ) -> None:
        """Draw a solid line."""
        self._draw_line(draw, self.canvas_points, width=width, fill=color, extend_by=extend_by)

    def _draw_arc(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, width, color, extend_by_deg: float = 0):
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

        if len(self.canvas_points) != 3:
            raise SegmentError("'ARC' segments need EXACTLY 3 (three) points, no more, no less!")

        cx1, cy1 = self.canvas_points[0]
        cx2, cy2 = self.canvas_points[1]
        cx3, cy3 = self.canvas_points[2]

        # Operate in Cartesian mode
        cary1 = canvas.height - cy1
        cary2 = canvas.height - cy2
        cary3 = canvas.height - cy3
        circle: tuple[Point, float, bool]
        if (circle := fit_circle_cartes(cx1, cary1, cx2, cary2, cx3, cary3)) is None:
            return None
        center, radius, countercw = circle
        ang1 = math.degrees(math.atan2(cary1 - center.y, cx1 - center.x))
        ang2 = math.degrees(math.atan2(cary3 - center.y, cx3 - center.x))
        # End Cartesian mode, back to Canvas mode

        if not countercw:
            ang1, ang2 = ang2, ang1
        ang1 = 360.0 - ang1 - extend_by_deg
        ang2 = 360.0 - ang2 + extend_by_deg

        bx1, bx2 = sorted([(center.x - radius), (center.x + radius)])
        by1, by2 = sorted([(canvas.height - (center.y - radius)), (canvas.height - (center.y + radius))])
        bbox = (bx1, by1, bx2, by2)
        draw.arc(bbox, ang1, ang2, fill=color, width=width)

    def draw_black(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, extend_by: int = 3) -> None:
        """Draw using black color, with extension of segments."""
        if not self.canvas_points:
            return
        if self.mode == DrawMode.SOLID or self.mode == DrawMode.RAILS:
            self._draw_solid(draw, self.BlackWidth, (0, 0, 0), extend_by=extend_by)
        elif self.mode == DrawMode.DASHED:
            self._draw_dashed(draw, self.BlackWidth, (0, 0, 0), extend_by=extend_by)
        elif self.mode == DrawMode.ARC:
            self._draw_arc(canvas, draw, self.BlackWidth, (0, 0, 0), extend_by_deg=2)
        else:
            raise NotImplementedError()

    def draw_color(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, color: tuple[int, int, int]) -> None:
        """Draw with specified color."""
        if not self.canvas_points:
            return
        if self.mode == DrawMode.SOLID:
            self._draw_solid(draw, self.ColorWidth, color)
        elif self.mode == DrawMode.DASHED:
            self._draw_dashed(draw, self.ColorWidth, color)
        elif self.mode == DrawMode.RAILS:
            self._draw_rails(draw, self.ColorWidth, color)
        elif self.mode == DrawMode.ARC:
            self._draw_arc(canvas, draw, self.ColorWidth, color)
        else:
            raise NotImplementedError()

    def encode(self) -> SegmentSerialized:
        """Turn into data serializable by MessagePack."""
        return {
            "__mode": int(self.mode),
            "__color": self.color,
            "__points": [(p.x, p.y) for p in self.canvas_points],
        }

    def save(self, dest: Path) -> None:
        """Encode into MessagePack and save into file."""
        with dest.open("wb") as fout:
            msgpack.pack(self.encode(), fout)

    @classmethod
    def from_raw(cls, raw: SegmentSerialized) -> Self:
        """Instantiate from raw serialized data."""
        mode = DrawMode(raw["__mode"])
        colr = raw["__color"]
        o = cls(mode, colr)
        o.canvas_points = [Point(*i) for i in raw["__points"]]
        return o

    @classmethod
    def load(cls, source: Path) -> Self:
        """Load from a MessagePack file."""
        with source.open("rb") as fin:
            raw = msgpack.unpack(fin)
        return cls.from_raw(raw)
