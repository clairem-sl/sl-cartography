# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import datetime
import re
from collections import defaultdict
from pathlib import Path
from typing import cast

from pytz import timezone

from cartographer.roadmapper.colors import ALL_COLORS
from cartographer.roadmapper.road import Segment, DrawMode, Point
from sl_maptools import MapCoord
from sl_maptools.knowns import KNOWN_AREAS


SLT_TIMEZONE = "US/Pacific"

RE_TS = re.compile(
    r"(?P<year>\d{4})[/-]?(?P<month>\d{2})[/-]?(?P<day>\d{2})"
    r"\D+"
    r"(?P<hour>\d{2})\D?(?P<minute>\d{2})(?:\D?(?P<second>\d{2}))?"
)

RE_VECTOR = re.compile(r"\s*<\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)\s*>\s*")
RE_POSREC_LINE = re.compile(r"(?P<prefix>.*?)PosRecorder\s*(?P<ver>[^:]*):\s+(?P<entry>.*)")
RE_POSREC_KV = re.compile(r"(?P<key>[^:\s]+)\s*:\s*(?P<value>.*)")

IGNORED_COMMANDS = {"start", "stop", "width", "pos"}


class Command:
    def __init__(self, command: str, value: str, source: tuple[str, int] = (None, -1)):
        self.command = command
        self.value = value
        self.source = source

    @property
    def kvp(self):
        return self.command, self.value


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
        self.reg_corner: tuple[int, int, int] = cast(tuple[int, int, int], tuple(map(roundf, matches.groups())))

        if (matches := RE_VECTOR.match(local_pos)) is None:
            raise ValueError(f"Can't parse local_pos = '{local_pos}'")
        self.local_pos: tuple[int, int, int] = cast(tuple[int, int, int], tuple(map(roundf, matches.groups())))

    def __str__(self):
        return f"{self.region};;{self.parcel};;{self.reg_corner};;{self.local_pos}"

    def __repr__(self):
        return f"PosRecord('{self.region}', '{self.parcel}', {self.reg_corner}, {self.local_pos})"


def bake(
    recs: list[PosRecord | tuple[str, str]],
    saved_routes: dict[str, dict[str, list[Segment]]],
):
    bounds = set()
    continent = None
    route = None
    casefolded = {k.casefold(): k for k in KNOWN_AREAS.keys()}
    all_routes: dict[str, dict[str, list[Segment]]] = defaultdict(lambda: defaultdict(list))
    if saved_routes:
        for conti, routes in saved_routes.items():
            for route, segments in routes.items():
                all_routes[conti][route].extend(segments)
    segment = Segment(DrawMode.SOLID)
    doubled = False
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
                    if color_name not in ALL_COLORS:
                        print(f"    WARNING: Unknown Color {color_name} on {rec.source}")
                    segment.color = ALL_COLORS.get(color_name)
                case "mode", umode:
                    umode: str
                    wmode: DrawMode = DrawMode[umode.upper()]
                    if segment.mode != wmode:
                        all_routes[continent][route].append(segment)
                        segment = Segment(DrawMode.SOLID, color=segment.color)
                case "solid", _:
                    if segment.mode == DrawMode.DASHED:
                        all_routes[continent][route].append(segment)
                        segment = Segment(DrawMode.SOLID, color=segment.color)
                case "dashed", _:
                    if segment.mode == DrawMode.SOLID:
                        all_routes[continent][route].append(segment)
                        segment = Segment(DrawMode.DASHED, color=segment.color)
                case "endroute", _:
                    print(f"  {continent}::{route} ends...")
                    all_routes[continent][route].append(segment)
                    route = None
                    segment = Segment(DrawMode.SOLID)
                case "break", _:
                    print(f"    Discontinuous break!")
                    all_routes[continent][route].append(segment)
                    segment = Segment(DrawMode.SOLID, color=segment.color)
                case "doubled", onoff:
                    doubled = (onoff == "on")
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
                raise ValueError(f"Region '{rec.region}' outside of continent '{continent}' at {rec.source}")
            offset_tiles: MapCoord = coord - MapCoord(bounds[0], bounds[1])
            offset_pixels = offset_tiles * 256
            canv_x = offset_pixels.x + rec.local_pos[0]
            canv_y = (bounds.height * 256) - offset_pixels.y - rec.local_pos[1]
            segment.add_point(Point(canv_x, canv_y), add_halfway=doubled)

    # If last route is not 'endroute'd, it's probably not yet appended
    # So we append it now.
    if route:
        all_routes[continent][route].append(segment)

    # Remove segments that has empty list of points
    # Probably result of some 'endroute' and 'route' mishaps
    clean_routes: dict[str, dict[str, list[Segment]]] = defaultdict(lambda: defaultdict(list))
    for conti, routes in all_routes.items():
        for route, segments in routes.items():
            new_segs: list[Segment] = []
            # Removal of dupe canvas_points
            for seg in segments:
                seen = set()
                uniqs = []
                for p in seg.canvas_points:
                    if p in seen:
                        continue
                    seen.add(p)
                    uniqs.append(p)
                # If we end up with too few points, skip adding this segment
                if len(uniqs) < 2:
                    continue
                seg.canvas_points = uniqs
                new_segs.append(seg)
            if new_segs:
                clean_routes[conti][route] = new_segs

    return clean_routes


def parse_chat(chatfile: Path, recs: list[PosRecord | Command], start_from: datetime.datetime = None) -> bool:
    found_err = False
    lnum = -1
    skips = 0
    try:
        with chatfile.open("rt", encoding="utf-8") as fin:
            for lnum, ln in enumerate(fin, start=1):
                ln = ln.strip()

                if start_from and (mm := RE_TS.search(ln[:24])):
                    dd = {k: int(v) for k, v in mm.groupdict(0).items()}
                    dt = datetime.datetime(**dd, tzinfo=timezone(SLT_TIMEZONE))
                    if dt < start_from:
                        skips += 1
                        continue
                if skips:
                    print(f"Skipped {skips} lines...")
                    skips = 0

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
                    cmd, *rest = cmdline.casefold().split()
                    recs.append(Command(cmd, " ".join(rest), src))
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
    except UnicodeDecodeError:
        print(f"UnicodeDecodeError on {fin.name}:{lnum}")
        raise
    # pprint(recs)
    return found_err
