# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from enum import IntEnum
from pathlib import Path
from typing import NamedTuple, TypedDict

import msgpack
from PIL import ImageDraw


class DrawMode(IntEnum):
    SOLID = 1
    DASHED = 2


class SegmentSerialized(TypedDict):
    __mode: int
    __color: None | tuple[int, int, int]
    __points: list[tuple[int, int]]


class Point(NamedTuple):
    x: int
    y: int


class Segment:
    BlackWidth = 35
    ColorWidth = 25

    def __init__(self, mode: DrawMode, color: tuple[int, int, int] = None):
        self.mode: DrawMode = mode
        self.color: None | tuple[int, int, int] = color
        self.points: list[Point] = []

    def __repr__(self):
        return f"Segment(" f"{self.mode}, " f"{self.color}, " f"{self.points}" f")"

    def add(self, point: Point):
        self.points.append(point)

    def _draw_dashed(
        self,
        draw: ImageDraw.ImageDraw,
        width: int,
        color: tuple[int, int, int],
        start_blank: bool = True,
        dash_len: int = 6,
        blank_len: int = 4,
    ):
        c = -1 if (blank := start_blank) else 0
        piece_points: list[Point] = []
        blank_len -= 1
        dash_len += 1
        for point in self.points:
            c += 1
            if blank:
                if c >= blank_len:
                    c = 0
                    blank = False
                continue
            piece_points.append(point)
            if c >= dash_len:
                draw.line(piece_points, width=width, fill=color, joint="curve")
                c = 0
                blank = True
                piece_points.clear()
        if not blank and piece_points:
            draw.line(piece_points, width=width, fill=color, joint="curve")

    def _draw_solid(self, draw: ImageDraw.ImageDraw, width: int, color: tuple[int, int, int]):
        draw.line(self.points, width=width, fill=color, joint="curve")

    def draw_black(self, draw: ImageDraw.ImageDraw):
        if not self.points:
            return
        if self.mode == DrawMode.SOLID:
            self._draw_solid(draw, self.BlackWidth, (0, 0, 0))
        elif self.mode == DrawMode.DASHED:
            self._draw_dashed(draw, self.BlackWidth, (0, 0, 0))
        else:
            raise NotImplementedError()

    def draw_color(self, draw: ImageDraw.ImageDraw, color: tuple[int, int, int]):
        if not self.points:
            return
        if self.mode == DrawMode.SOLID:
            self._draw_solid(draw, self.ColorWidth, color)
        elif self.mode == DrawMode.DASHED:
            self._draw_dashed(draw, self.ColorWidth, color)
        else:
            raise NotImplementedError()

    def encode(self):
        return {
            "__mode": int(self.mode),
            "__color": self.color,
            "__points": [(p.x, p.y) for p in self.points],
        }

    def save(self, dest: Path):
        with dest.open("wb") as fout:
            msgpack.pack(self.encode(), fout)

    @classmethod
    def from_raw(cls, raw: SegmentSerialized):
        mode = DrawMode(raw["__mode"])
        colr = raw["__color"]
        o = cls(mode, colr)
        o.points = [Point(*i) for i in raw["__points"]]
        return o

    @classmethod
    def load(cls, source: Path):
        with source.open("rb") as fin:
            raw = msgpack.unpack(fin)
        return cls.from_raw(raw)
