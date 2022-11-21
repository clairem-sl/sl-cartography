# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import itertools
import re
import sys
from collections import defaultdict
from enum import IntEnum
from pathlib import Path
from pprint import PrettyPrinter
from typing import cast, TextIO, NamedTuple, TypedDict

from PIL import Image, ImageDraw

from cartographer.roadmapper.config import options, SAVE_DIR
from sl_maptools import MapCoord
from sl_maptools.knowns import KNOWN_AREAS


DEBUG = False


RE_POSREC_LINE = re.compile(
    r"\[\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{1,2}]\s+PosRecorder:\s+(.*)"
)
RE_POSREC_KV = re.compile(r"(?P<key>[^:\s]+)\s*:\s*(?P<value>.*)")
RE_VECTOR = re.compile(r"\s*<\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\s*>\s*")

POSREC_COMMANDS = {"start", "stop", "endroute", "solid", "dashed", "break"}


class DrawMode(IntEnum):
    SOLID = 1
    DASHED = 2


class Point(NamedTuple):
    x: int
    y: int


class PosRecord:
    def __init__(
        self,
        region_name: str,
        parcel_name: str | None,
        region_corner: str,
        local_pos: str,
        source: tuple[str, int] = (None, -1),
    ):
        self.region = region_name
        self.parcel = parcel_name
        self.source = source

        def roundf(num: str):
            return round(float(num))

        if (matches := RE_VECTOR.match(region_corner)) is None:
            raise ValueError(f"Can't parse region_corner = '{region_corner}'")
        self.reg_corner: tuple[int, int, int] = cast(
            tuple[int, int, int], tuple(map(roundf, matches.groups()))
        )

        if (matches := RE_VECTOR.match(local_pos)) is None:
            raise ValueError(f"Can't parse local_pos = '{local_pos}'")
        self.local_pos: tuple[int, int, int] = cast(
            tuple[int, int, int], tuple(map(roundf, matches.groups()))
        )

    def __str__(self):
        return f"{self.region};;{self.parcel};;{self.reg_corner};;{self.local_pos}"

    def __repr__(self):
        return f"PosRecord('{self.region}', '{self.parcel}', {self.reg_corner}, {self.local_pos})"


class Command:
    def __init__(self, command, value, source: tuple[str, int] = (None, -1)):
        self.command = command
        self.value = value
        self.source = source

    @property
    def kvp(self):
        return self.command, self.value


class SegmentSerialized(TypedDict):
    __mode: int
    __color: None | tuple[int, int, int]
    __points: list[tuple[int, int]]


class Segment:
    BlackWidth = 40
    ColorWidth = 30

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

    def _draw_solid(
        self, draw: ImageDraw.ImageDraw, width: int, color: tuple[int, int, int]
    ):
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

    @classmethod
    def from_raw(cls, raw: SegmentSerialized):
        mode = DrawMode(raw["__mode"])
        colr = raw["__color"]
        o = cls(mode, colr)
        o.points = [Point(*i) for i in raw["__points"]]
        return o


COLORS: dict[str, tuple[int, int, int]] = {
    # Source: https://www.schemecolor.com/party-pastels.php
    "celadon": (182, 230, 189),  # Celadon, greenish
    "blupurp": (172, 154, 241),  # Maximum Blue Purple
    "rose": (247, 200, 238),  # Classic Rose
    "banana": (255, 239, 176),  # Banana Mania
    "tangerine": (245, 154, 142),  # Vivid Tangerine
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
}


def execute(recs: list[PosRecord | tuple[str, str]]):
    cols = itertools.cycle(tuple(COLORS.values()))
    bounds = set()
    continent = None
    route = None
    mode: DrawMode = DrawMode.SOLID
    casefolded = {k.casefold(): k for k in KNOWN_AREAS.keys()}
    all_routes: dict[str, dict[str, list[Segment]]] = defaultdict(lambda: defaultdict(list))
    segment = Segment(mode)
    _col: tuple[int, int, int] = (0, 0, 0)
    for rec in recs:
        # print(rec)
        if isinstance(rec, Command):
            match rec.kvp:
                case "continent", conti:
                    if (continent := casefolded.get(conti.casefold())) is None:
                        raise ValueError(f"Unknown continent: {conti}")
                    print(f"Continent: {continent}")
                    bounds = KNOWN_AREAS[continent]
                    segment = Segment(DrawMode.SOLID)
                case "route", route:
                    print(f"  {continent}::{route} begins...")
                    segment = Segment(DrawMode.SOLID)
                case "color", color_name:
                    if color_name not in COLORS:
                        print(f"    WARNING: Unknown Color '{color_name}'! Will use standard cycle")
                    segment.color = COLORS.get(color_name)
                case "solid", _:
                    if mode == DrawMode.DASHED:
                        all_routes[continent][route].append(segment)
                        segment = Segment(DrawMode.SOLID)
                case "dashed", _:
                    if mode == DrawMode.SOLID:
                        all_routes[continent][route].append(segment)
                        segment = Segment(DrawMode.DASHED)
                case "endroute", _:
                    print(f"  {continent}::{route} ends...")
                    all_routes[continent][route].append(segment)
                    route = None
                    segment = Segment(DrawMode.SOLID)
                case "break", _:
                    print(f"    Discontinuous break!")
                    all_routes[continent][route].append(segment)
                    segment = Segment(DrawMode.SOLID)

        elif isinstance(rec, PosRecord):
            coord = MapCoord(rec.reg_corner[0] // 256, rec.reg_corner[1] // 256)
            if coord not in bounds:
                raise ValueError(
                    f"Region '{rec.region}' outside of continent '{continent}'"
                )
            coffs_tiles: MapCoord = coord - MapCoord(bounds[0], bounds[1])
            coffs_pixels = coffs_tiles * 256
            canv_x = coffs_pixels[0] + rec.local_pos[0]
            canv_y = (bounds.height * 256) - coffs_pixels[1] - rec.local_pos[1]
            segment.add(Point(canv_x, canv_y))

    for continent, lines in all_routes.items():
        print(f"Drawing continent {continent}...")
        cont_img = SAVE_DIR / (continent + ".png")
        with cont_img.open("rb") as fin:
            im = Image.open(fin)
            canvas = Image.new("RGBA", im.size)
        draw = ImageDraw.Draw(canvas)

        print("  Drawing Black Outlines...")
        for portions in lines.values():
            for seg in portions:
                seg.draw_black(draw)

        for route, portions in lines.items():
            print(f"  Drawing {route}...")
            while (color := next(cols)) == _col:
                pass
            for seg in portions:
                _col = seg.color or color
                seg.draw_color(draw, _col)

        if canvas:
            roadpath = SAVE_DIR / (continent + "_Roads.png")
            print(f"    Saving to {roadpath}")
            canvas.save(roadpath)


def parse_stream(fin: TextIO, recs: list[PosRecord | Command]) -> bool:
    found_err = False
    for lnum, ln in enumerate(fin, start=1):
        ln = ln.strip()
        if (matches := RE_POSREC_LINE.match(ln)) is None:
            continue
        posrec_dat = matches[1]

        if posrec_dat.startswith("#"):
            continue

        src = (fin.name, lnum)

        if posrec_dat.startswith("3;;"):
            items = posrec_dat.split(";;")[1:]
        elif "**" in posrec_dat:
            items = posrec_dat.split("**")
        elif "*<" in posrec_dat:
            items = posrec_dat.split("*")
        elif (matches := RE_POSREC_KV.match(posrec_dat)) is not None:
            cmd = Command(matches["key"], matches["value"], src)
            recs.append(cmd)
            continue
        elif (_cf := posrec_dat.casefold()) in POSREC_COMMANDS:
            cmd = Command(_cf, "", src)
            recs.append(cmd)
            continue
        else:
            print(f"ERROR: Unrecognized syntax on line {lnum}")
            print(">>>", ln)
            found_err = True
            continue

        match items:
            case [regn, regc, locp]:
                record = PosRecord(regn, None, regc, locp, source=src)
            case [regn, parn, regc, locp]:
                record = PosRecord(regn, parn, regc, locp, source=src)
            case _:
                print(f"ERROR: Unrecognized syntax on line {lnum}")
                print(">>>", ln)
                found_err = True
                continue

        recs.append(record)
    # pprint(recs)
    return found_err


def main(recfiles: list[Path]):
    all_recs = []
    err = False
    for recfile in recfiles:
        if not recfile.exists():
            print(f"{recfile} not found!")
            sys.exit(1)
        print(f"Parsing {recfile}...")
        with recfile.open("rt") as fin:
            err |= parse_stream(fin, all_recs)
    if DEBUG:
        pp = PrettyPrinter(width=160)
        pp.pprint(all_recs)
    execute(all_recs)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
