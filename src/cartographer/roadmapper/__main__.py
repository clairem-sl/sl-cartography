# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import itertools
import sys
from pathlib import Path
from pprint import PrettyPrinter

from PIL import Image, ImageDraw

from cartographer.roadmapper.colors import AUTO_COLORS
from cartographer.roadmapper.config import SAVE_DIR, options
from cartographer.roadmapper.parse.__main__ import parse_stream, bake
from cartographer.roadmapper.road import Segment
from cartographer.roadmapper.yaml import load_from_yaml
from sl_maptools.knowns import KNOWN_AREAS

DEBUG = False


def do_draw(all_routes: dict[str, dict[str, list[Segment]]]):
    cols = itertools.cycle(tuple(AUTO_COLORS.values()))
    _col: tuple[int, int, int] = (-1, -1, -1)

    for continent, lines in all_routes.items():
        print(f"Drawing continent {continent}...")
        bounds = KNOWN_AREAS[continent]
        canvas = Image.new("RGBA", (bounds.width * 256, bounds.height * 256))
        draw = ImageDraw.Draw(canvas)

        print("  Drawing Black Outlines...")
        for route, portions in lines.items():
            for segnum, seg in enumerate(portions, start=1):
                if len(seg.canvas_points) < 2:
                    print(f"    WARNING: Not enough data points at {continent}::{route}::{segnum}")
                    continue
                seg.draw_black(draw)

        for route, portions in lines.items():
            print(f"  Drawing {route}...")
            while (color := next(cols)) == _col:
                pass
            for segnum, seg in enumerate(portions, start=1):
                if len(seg.canvas_points) < 2:
                    print(f"    WARNING: Not enough data points at {continent}::{route}::{segnum}")
                    continue
                _col = seg.color or color
                seg.draw_color(draw, _col)

        if canvas:
            roadpath = SAVE_DIR / (continent + "_Roads.png")
            print(f"  ---\n  Saving to {roadpath}")
            canvas.save(roadpath)


def main(recfiles: list[Path], saveto: Path | None, readfrom: Path | None):
    saved_routes: dict[str, dict[str, list[Segment]]] = {}
    if readfrom is not None:
        if not readfrom.exists():
            raise FileNotFoundError(f"YAML_FILE {readfrom} not found!")
        saved_routes = load_from_yaml(readfrom)

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

    final_routes = bake(all_recs, saved_routes, saveto)
    do_draw(final_routes)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
