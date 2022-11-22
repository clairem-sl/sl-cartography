# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from pathlib import Path
from typing import Any, TypedDict

from ruamel import yaml as ryaml
from ruamel.yaml.representer import Representer

from cartographer.roadmapper.road import DrawMode, Point, Segment


def load_from_yaml(yaml_file: Path) -> dict[str, dict[str, list[Segment]]]:
    all_routes: dict[str, dict[str, list[Segment]]] = {}

    with yaml_file.open("rt") as fin:
        data: dict[str, Any] = ryaml.safe_load(fin)

    class SegmentStruct(TypedDict):
        mode: str
        color: list[int, int, int] | None
        points: list[list[int, int]]

    road_data: list[dict[str, Any]] = data["road_data"]
    for rd in road_data:
        continent = rd["continent"]
        all_routes[continent] = {}
        routes: list[dict[str, Any]] = rd["routes_data"]
        for route in routes:
            segs = []
            all_routes[continent][route["route_name"]] = segs
            segments: list[SegmentStruct] = route["segments"]
            for segment in segments:
                mode = DrawMode[segment["mode"].upper()]
                if color := segment["color"]:
                    color = tuple(color)
                new_seg = Segment(mode=mode, color=color)
                points: list[list[int, int]] = segment["points"]
                new_seg.points = [Point(*p) for p in points]
                segs.append(new_seg)

    return all_routes


def tuple_as_seq(self: Representer, data):
    """Make tuple looks like a horizontal list"""
    # Adapted from: https://stackoverflow.com/a/39611010/149900
    return self.represent_sequence(
        "tag:yaml.org,2002:seq",
        data,
        flow_style=True,
    )


def save_to_yaml(yaml_file: Path, all_routes: dict[str, dict[str, list[Segment]]]):
    road_data = []
    for continent, routes in all_routes.items():
        routes_data = []
        for route, segments in routes.items():
            segments_data = []
            for segment in segments:
                points_data: list[list[int, int]] = [list(p) for p in segment.points]
                segments_data.append({"mode": segment.mode.name, "color": segment.color, "points": points_data})
            routes_data.append({"route_name": route, "segments": segments_data})
        road_data.append({"continent": continent, "routes": routes_data})
    data = {"road_data": road_data}
    old_representer = Representer.represent_tuple
    try:
        Representer.represent_tuple = tuple_as_seq
        with yaml_file.open("wt") as fout:
            ryaml.dump(data, fout, allow_unicode=True)
    finally:
        Representer.represent_tuple = old_representer
