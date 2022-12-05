# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pathlib import Path
from typing import Any

import ruamel.yaml as ryaml

from roadmapper_v3.model import Continent, Point, Route, Segment, SegmentMode


def decode(raw_data: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Continent]:
    road_data: dict[str, dict[str, dict[str, Any]]] = raw_data["road_data"]
    assert isinstance(road_data, dict)
    all_routes = {}
    for cont_name, routes in road_data.items():
        continent = Continent(cont_name)
        all_routes[cont_name] = continent
        for rout_name, route_data in routes.items():
            color = tuple(route_data["color"]) if route_data["color"] else None
            route = Route(rout_name, color)
            segments: list[dict[str, Any]] = route_data["segments"]
            for seg_data in segments:
                mode = SegmentMode[seg_data["mode"].upper()]
                segment = Segment(mode, desc=seg_data.get("desc"), width=seg_data.get("width"))
                for x, y in seg_data["geo_points"]:
                    segment.add_point(Point(x, y))
                route.add_segment(segment)
            continent.add_route(route)
    return all_routes


def load_from(yaml_file: Path) -> dict[str, Continent]:
    if not yaml_file.exists():
        raise FileNotFoundError()
    with yaml_file.open("rt", encoding="utf-8") as fin:
        data = ryaml.safe_load(fin)
    assert isinstance(data, dict)
    assert "version" in data
    assert data["version"] == 2
    assert "road_data" in data
    return decode(data)


def encode(all_routes: dict[str, Continent]) -> dict[str, dict[str, dict[str, Any]]]:
    road_data = {}
    for cont_name, continent in all_routes.items():
        cont_data = {}
        road_data[cont_name] = cont_data
        for rout_name, route in continent.routes.items():
            rout_seg_list = []
            rout_data = {
                "color": route.color,
                "segments": rout_seg_list,
            }
            cont_data[rout_name] = rout_data
            for segment in route.segments:
                seg_data = {
                    "mode": segment.mode.name,
                    "desc": segment.desc,
                    "width": segment.width,
                    "geo_points": [(p.x, p.y) for p in segment.geopoints],
                }
                rout_seg_list.append(seg_data)
    return {
        "version": 2,
        "road_data": road_data,
    }


class RoadRepresenter(ryaml.RoundTripRepresenter):
    def ignore_aliases(self, data):  # type: (Any) -> bool
        return True

    def represent_data(self, data):  # type: (Any) -> Any
        if isinstance(data, tuple):
            return self.represent_sequence("tag:yaml.org,2002:seq", list(data), flow_style=True)
        return super().represent_data(data)


def save_to(yaml_file: Path, all_routes: dict[str, Continent]):
    yml = ryaml.YAML()
    yml.default_flow_style = None
    yml.Representer = RoadRepresenter
    with yaml_file.open("wt", encoding="utf-8") as fout:
        yml.dump(encode(all_routes), fout)
    print(f"Routes saved to {yaml_file}")
