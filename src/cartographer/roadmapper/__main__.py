# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import itertools
import re
import sys
from collections import defaultdict
from pathlib import Path
from pprint import PrettyPrinter
from typing import cast, TextIO, TypedDict

from PIL import Image, ImageDraw

from cartographer.roadmapper.config import options, SAVE_DIR
from cartographer.roadmapper.road import Segment, DrawMode, Point
from sl_maptools import MapCoord
from sl_maptools.knowns import KNOWN_AREAS


DEBUG = False


RE_POSREC_LINE = re.compile(
    r"(?P<prefix>.*?)PosRecorder\s*(?P<ver>[^:]*):\s+(?P<entry>.*)"
)
RE_POSREC_KV = re.compile(r"(?P<key>[^:\s]+)\s*:\s*(?P<value>.*)")
RE_VECTOR = re.compile(r"\s*<\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)\s*>\s*")

IGNORED_COMMANDS = {"start", "stop", "width", "pos"}


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
    _col: tuple[int, int, int] = (-1, -1, -1)
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
                    route = None
                case "route", route_new:
                    if route is not None:
                        all_routes[continent][route].append(segment)
                    route = route_new
                    print(f"  {continent}::{route} begins...")
                    segment = Segment(DrawMode.SOLID)
                case "color", color_name:
                    if color_name not in COLORS:
                        print(f"    WARNING: Unknown Color '{color_name}' on {rec.source}")
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
                case cmd, _:
                    if cmd not in IGNORED_COMMANDS:
                        print(f"    WARNING: Unrecognized command {rec.kvp} from {rec.source}")

        elif isinstance(rec, PosRecord):
            if continent is None:
                print(f"WARNING: PosRecord found but continent not set, at {rec.source}")
                continue
            if route is None:
                print(f"WARNING: PosRecord found but route not set, at {rec.source}")
                continue
            coord = MapCoord(rec.reg_corner[0] // 256, rec.reg_corner[1] // 256)
            if coord not in bounds:
                raise ValueError(
                    f"Region '{rec.region}' outside of continent '{continent}' at {rec.source}"
                )
            offset_tiles: MapCoord = coord - MapCoord(bounds[0], bounds[1])
            offset_pixels = offset_tiles * 256
            canv_x = offset_pixels.x + rec.local_pos[0]
            canv_y = (bounds.height * 256) - offset_pixels.y - rec.local_pos[1]
            segment.add(Point(canv_x, canv_y))

    for continent, lines in all_routes.items():
        print(f"Drawing continent {continent}...")
        bounds = KNOWN_AREAS[continent]
        canvas = Image.new("RGBA", (bounds.width * 256, bounds.height * 256))
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
            print(f"  Saving to {roadpath}")
            canvas.save(roadpath)


def parse_stream(fin: TextIO, recs: list[PosRecord | Command]) -> bool:
    found_err = False
    lnum = -1
    try:
        for lnum, ln in enumerate(fin, start=1):
            ln = ln.strip()
            if (matches := RE_POSREC_LINE.match(ln)) is None:
                continue
            cmdline = matches["entry"]

            if cmdline.startswith("#"):
                continue

            src = (fin.name, lnum)

            if cmdline.startswith("3;;"):
                items = cmdline.split(";;")[1:]
            elif "**" in cmdline:
                items = cmdline.split("**")
            elif "*<" in cmdline:
                items = cmdline.split("*")
            elif (matches := RE_POSREC_KV.match(cmdline)) is not None:
                cmd = Command(matches["key"], matches["value"], src)
                recs.append(cmd)
                continue
            else:
                cmd = Command(cmdline.casefold(), "", src)
                recs.append(cmd)
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
    except UnicodeDecodeError as ude:
        print(f"UnicodeDecodeError on {fin.name}:{lnum}")
        raise
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
        with recfile.open("rt", encoding="utf-8") as fin:
            err |= parse_stream(fin, all_recs)
    if err:
        print("Errors found. Please fix them first!")
        sys.exit(1)
    if DEBUG:
        pp = PrettyPrinter(width=160)
        pp.pprint(all_recs)
    execute(all_recs)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
