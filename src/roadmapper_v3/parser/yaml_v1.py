# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pathlib import Path
from pprint import pprint

import ruamel.yaml as ryaml

from roadmapper_v3.model import Continent, Point, Route, Segment, SegmentMode
from roadmapper_v3.model.yaml import save_to


def load_from_v1(yaml_file: Path):
    if not yaml_file.exists():
        raise FileNotFoundError()
    with yaml_file.open("rt", encoding="utf-8") as fin:
        data = ryaml.safe_load(fin)
    assert "version" in data
    assert data["version"] == 1
    assert "road_data" in data

    new_data: dict[str, Continent] = {}

    for road_datum in data["road_data"]:
        assert isinstance(road_datum, dict)
        conti_name = road_datum["continent"]
        continent = Continent(conti_name)
        for route_datum in road_datum["routes"]:
            assert isinstance(route_datum, dict)
            route_name = route_datum["route_name"]
            assert route_name not in continent
            route = Route(route_name)
            for seg_datum in route_datum["segments"]:
                assert isinstance(seg_datum, dict)
                if seg_datum["color"] is not None:
                    assert len(seg_datum["color"]) == 3
                    try:
                        new_color = tuple(seg_datum["color"])
                        if route.color is not None and route.color != new_color:
                            print(f"WARNING: Color for {route.name} is redefined!")
                            print(f"    {route.color} -> {new_color}")
                        route.color = new_color
                    except Exception:
                        print(seg_datum)
                        raise
                segment = Segment(mode=SegmentMode[seg_datum["mode"].upper()])
                for cx, cy in seg_datum["canv_points"]:
                    gx, gy = cx, continent.canvas_height - cy
                    gx += 256.0 * continent.west_t
                    gy += 256.0 * continent.south_t
                    segment.add_point(Point(gx, gy))
                route.add_segment(segment, raises=False)
            continent.add_route(route)
        new_data[conti_name] = continent

    return new_data


def main():
    data = load_from_v1(Path(r"C:\Repos\sl-cartography-claire\src\roadmap.yaml"))
    pprint(data)
    save_to(Path(r"C:\Repos\sl-cartography-pep\roadmap_v2.yaml"), data)


if __name__ == "__main__":
    main()
