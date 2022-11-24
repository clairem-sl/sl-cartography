# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from pathlib import Path
from typing import Any, TypedDict

import ruamel.yaml as ryaml

from cartographer.roadmapper.road import DrawMode, Point, Segment


def load_from_yaml(yaml_file: Path) -> dict[str, dict[str, list[Segment]]]:
    all_routes: dict[str, dict[str, list[Segment]]] = {}

    with yaml_file.open("rt") as fin:
        data: dict[str, Any] = ryaml.safe_load(fin)

    class SegmentStruct(TypedDict):
        mode: str
        color: list[int, int, int] | None
        canv_points: list[list[int, int]]

    class RouteStruct(TypedDict):
        route_name: str
        segments: list[SegmentStruct]

    road_data: list[dict[str, Any]] = data["road_data"]
    for rd in road_data:
        continent = rd["continent"]
        all_routes[continent] = {}
        routes: list[RouteStruct] = rd["routes"]
        for route in routes:
            segs = []
            for segment in route["segments"]:
                mode = DrawMode[segment["mode"].upper()]
                color: tuple[int, int, int] | None
                if color := segment["color"]:
                    color = tuple(color)
                new_seg = Segment(mode=mode, color=color)
                new_seg.canvas_points = [Point(*p) for p in segment["canv_points"]]
                segs.append(new_seg)
            all_routes[continent][route["route_name"]] = segs

    return all_routes


class MyRepresenter(ryaml.RoundTripRepresenter):
    def ignore_aliases(self, data):  # type: (Any) -> bool
        return True

    def represent_data(self, data):  # type: (Any) -> Any
        if isinstance(data, tuple):
            return self.represent_sequence("tag:yaml.org,2002:seq", list(data), flow_style=True)
        return super().represent_data(data)


def save_to_yaml(yaml_file: Path, all_routes: dict[str, dict[str, list[Segment]]]):
    road_data = []
    for continent, routes in all_routes.items():
        routes_data = []
        for route, segments in routes.items():
            segments_data = []
            for segment in segments:
                segments_data.append(
                    {"mode": segment.mode.name, "color": segment.color, "canv_points": segment.canvas_points}
                )
            routes_data.append({"route_name": route, "segments": segments_data})
        road_data.append({"continent": continent, "routes": routes_data})
    data = {"road_data": road_data}
    try:
        yml = ryaml.YAML()
        yml.default_flow_style = None
        yml.Representer = MyRepresenter
        with yaml_file.open("wt") as fout:
            yml.dump(data, fout)
        print(f"Routes saved to {yaml_file}")
    finally:
        pass
