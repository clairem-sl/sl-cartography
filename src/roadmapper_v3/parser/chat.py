# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import argparse
import datetime
import math
import re
from pathlib import Path

from roadmapper_v3.draw import Point
from roadmapper_v3.draw.colors import ALL_COLORS
from roadmapper_v3.model import Continent, Route, Segment, SegmentMode
from roadmapper_v3.model.yaml import load_from, save_to

RE_TS = re.compile(
    r"(?P<year>\d{4})[/-]?(?P<month>\d{1,2})[/-]?(?P<day>\d{1,2})"
    r"\D+"
    r"(?P<hour>\d{1,2})\D?(?P<minute>\d{2})(?:\D?(?P<second>\d{2}))?"
)
RE_VECTOR = re.compile(r"\s*<\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)\s*>\s*")
RE_POSREC_LINE = re.compile(r"(?P<prefix>.*?)PosRecorder\s*(?P<ver>[^:]*):\s+(?P<entry>.*)")
RE_POSREC_KV = re.compile(r"(?P<key>[^:\s]+)\s*:\s*(?P<value>.*)")
RE_SEPARATOR = re.compile(r"[;,\s]+")


def options():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--startfrom",
        "-s",
        metavar="START_TS",
        default="",
        help="Timestamp to start parsing",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="YAML_FILE",
        type=Path,
        required=True,
        help="Output YAML file",
    )
    parser.add_argument(
        "chat_file",
        type=Path,
        nargs="+",
        help="Chat transcript file",
    )
    return parser.parse_args()


class ChatLine:
    __slots__ = ("source_path", "source_line")

    def __init__(self, spath, sline):
        self.source_path: Path = spath
        self.source_line: str = sline

    @property
    def source(self) -> str:
        return f"{self.source_path}::{self.source_line}"


class PosRecord(ChatLine):
    __slots__ = ("region_name", "parcel_name", "region_corner", "pos_local")

    # noinspection PyUnusedLocal
    def __init__(self, ver, regname, parname, regcorner, pos, *args, spath: Path, sline: int):
        super().__init__(spath, sline)
        self.region_name = regname
        self.parcel_name = parname
        if (matches := RE_VECTOR.match(regcorner)) is None:
            raise ValueError(f"Can't parse region corner: {regcorner}")
        self.region_corner = tuple(map(float, matches.groups()))
        if (matches := RE_VECTOR.match(pos)) is None:
            raise ValueError(f"Can't parse position: {pos}")
        self.pos_local = tuple(map(float, matches.groups()))

    def to_point(self) -> Point:
        xr, yr, zr = self.region_corner
        xp, yp, zp = self.pos_local
        return Point(xr + xp, yr + yp)


class ChatCommand(ChatLine):
    def __init__(self, command: str, args: str = "", *, spath: Path, sline: int):
        super().__init__(spath, sline)
        self.command = command.strip().casefold()
        self.args = args.strip()

    def as_tuple(self) -> tuple[str, str]:
        return self.command, self.args


def parse(chat_file: Path, startfrom: str) -> list[PosRecord | ChatCommand]:
    if not chat_file.exists():
        raise FileNotFoundError(f"File not found: {chat_file}")

    if startfrom:
        if (matches := RE_TS.match(startfrom)) is None:
            raise ValueError(f"Unrecognized timestamp format: {startfrom}")
        start_ts = datetime.datetime(**matches.groupdict())
    else:
        start_ts = datetime.datetime(2000, 1, 1, 0, 0, 0)

    parsed: list[PosRecord | ChatCommand] = []
    with chat_file.open("rt", encoding="utf-8") as fin:
        for lnum, ln in enumerate(fin, start=1):
            ln = ln.strip()
            if (matches := RE_POSREC_LINE.match(ln)) is None:
                continue
            entry = matches["entry"]
            if entry.startswith("#"):
                continue
            match_ts = RE_TS.search(matches["prefix"])
            ln_ts = datetime.datetime(**{k: int(v) for k, v in match_ts.groupdict().items() if v})
            if ln_ts < start_ts:
                continue
            if entry.startswith("3;;"):
                pos_record = PosRecord(*entry.split(";;"), spath=chat_file, sline=lnum)
                parsed.append(pos_record)
                continue
            elems = entry.split(":", maxsplit=1)
            command = ChatCommand(*elems, spath=chat_file, sline=lnum)
            parsed.append(command)

    return parsed


IGNORED_COMMANDS = {"pos", "endroute", "start", "stop"}


def bake(parsed: list[PosRecord | ChatCommand]):
    all_roads: dict[str, Continent] = {}
    continent: Continent | None = None
    route: Route | None = None
    segment = Segment()

    def new_segment(mode: SegmentMode = SegmentMode.SOLID):
        nonlocal segment
        if len(segment.geopoints) > 1:
            route.add_segment(segment)
        segment = Segment(mode=mode)

    prev_point = Point(math.nan, math.nan)
    parsed_iter = iter(parsed)
    while True:
        try:
            p = next(parsed_iter)
        except StopIteration:
            break

        if isinstance(p, ChatCommand):
            match p.as_tuple():
                case "continent", name:
                    continent = all_roads.setdefault(name, Continent(name))
                case "route", name:
                    if route and len(segment.geopoints) >= 2:
                        route.add_segment(segment)
                    if name in continent:
                        route = continent[name]
                    else:
                        continent.add_route((route := Route(name)))
                    segment = Segment()
                case "color", region_color:
                    elems = RE_SEPARATOR.split(region_color)
                    if len(elems) == 3:
                        try:
                            rgb = tuple(int(c) for c in elems)
                        except ValueError:
                            print(f"WARNING: Invalid number: {elems}")
                            continue
                        if not all(map(lambda x: 0 <= x <= 255, rgb)):
                            print(f"WARNING: One of the RGB values are outside allowable range of 0~255: {rgb}")
                        else:
                            route.color = rgb
                    else:
                        if region_color not in ALL_COLORS:
                            print(f"WARNING: Color name '{region_color}' not recognised ({p.source})")
                        route.color = ALL_COLORS.get(region_color)
                case "segdesc", segment_desc:
                    segment.desc = segment_desc
                case "mode", new_mode:
                    try:
                        new_mode = SegmentMode[new_mode]
                    except KeyError:
                        raise KeyError(f"Unrecognized mode '{new_mode}' ({p.source})")
                    if new_mode != segment.mode:
                        new_segment(new_mode)
                case "break", _:
                    new_segment()
                case "solid", _:
                    if segment.mode != SegmentMode.SOLID:
                        new_segment(mode=SegmentMode.SOLID)
                case "dashed", _:
                    if segment.mode != SegmentMode.DASHED:
                        new_segment(mode=SegmentMode.DASHED)
                case "arc", _:
                    new_segment(mode=SegmentMode.ARC)
                    for _ in range(3):
                        while not isinstance((rec := next(parsed_iter)), PosRecord):
                            pass
                        segment.add_point(rec.to_point())
                    new_segment()
                case other, _:
                    if other not in IGNORED_COMMANDS:
                        print(f"WARNING: Unrecognized command '{other}' ({p.source})")

        elif isinstance(p, PosRecord):
            if not continent.contains_geo((geop := p.to_point())):
                print(f"WARNING: Coordinates {geop} outside of continent '{continent.name}' ({p.source})")
            if geop.is_close(prev_point):
                continue
            segment.add_point(geop)
            prev_point = geop

        else:
            raise ValueError(f"Unrecognized parsed token <{type(p)}>{p}")

    if segment.geopoints:
        route.add_segment(segment)

    return all_roads


def main(output: Path, chat_file: list[Path], startfrom: str):
    targ_dict: dict[str, Continent] = {}
    if output.exists():
        print(f"Output '{output}' exists, reading previous data for merging...")
        targ_dict = load_from(output)

    for cf in chat_file:
        print(f"Parsing {cf}...")
        parsed = parse(cf, startfrom)
        baked = bake(parsed)

        for conti_name, b_continent in baked.items():
            if conti_name not in targ_dict:
                targ_dict[conti_name] = b_continent
                print(f"New continent added: {conti_name}")
                continue
            targ_conti = targ_dict[conti_name]
            for route_name, b_route in b_continent.routes.items():
                if route_name not in targ_conti:
                    targ_conti.add_route(b_route)
                    print(f"New route added: {conti_name}::{route_name}")
                    continue
                targ_route = targ_conti[route_name]
                print(f"Checking new segments for {conti_name}::{route_name} ", end="", flush=True)
                for seg in b_route.segments:
                    if seg in targ_route:
                        continue
                    print("+", end="", flush=True)
                    targ_route.add_segment(seg)
                print()

    save_to(output, targ_dict)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
