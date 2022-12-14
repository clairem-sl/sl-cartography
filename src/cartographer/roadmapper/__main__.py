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
from cartographer.roadmapper.parse_chat import bake, parse
from cartographer.roadmapper.road import DrawMode, Segment
from cartographer.roadmapper.yaml import load_from_yaml, save_to_yaml
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import make_backup

DEBUG = False


def do_draw(all_routes: dict[str, dict[str, list[Segment]]]):
    cols = itertools.cycle(tuple(AUTO_COLORS.values()))
    _col: tuple[int, int, int] = (-1, -1, -1)

    progchar: dict[DrawMode, str] = {
        DrawMode.SOLID: ".",
        DrawMode.DASHED: "-",
        DrawMode.RAILS: "=",
        DrawMode.ARC: "/",
    }

    for continent, lines in all_routes.items():
        print(f"Drawing continent {continent}...")
        bounds = KNOWN_AREAS[continent]
        canvas = Image.new("RGBA", (bounds.width * 256, bounds.height * 256))
        draw = ImageDraw.Draw(canvas)

        route = "???"
        try:
            print("  Drawing Black Outlines...", end="", flush=True)
            for route, portions in lines.items():
                print(".", end="", flush=True)
                for segnum, seg in enumerate(portions, start=1):
                    if len(seg.canvas_points) < 2:
                        print(f"    WARNING: Not enough data points at {continent}::{route}::{segnum}")
                        continue
                    seg.draw_black(canvas, draw)
            print()

            for route, portions in lines.items():
                print(f"  Drawing {route}...", end="", flush=True)
                while (color := next(cols)) == _col:
                    pass
                segnum = 0
                for segnum, seg in enumerate(portions, start=1):
                    print(progchar[seg.mode], end="", flush=True)
                    if len(seg.canvas_points) < 2:
                        print(f"    WARNING: Not enough data points at {continent}::{route}::{segnum}")
                        continue
                    _col = seg.color or color
                    seg.draw_color(canvas, draw, _col)
                print(segnum)
        except Exception as e:
            print(f"ERROR: Exception <{type(e)}> processing {continent}::{route}")
            raise

        if canvas:
            roadpath = SAVE_DIR / (continent + "_Roads.png")
            print(f"  ---\n  Saving to {roadpath}")
            canvas.save(roadpath)


def main(readchat: list[Path], saveto: Path | None, yamlfiles: list[Path]):
    saved_routes: dict[str, dict[str, list[Segment]]] = {}
    readchat = [] if readchat is None else readchat

    for yf in yamlfiles:
        if not yf.exists():
            raise FileNotFoundError(f"YAML_FILE {yf} not found!")
        saved_routes.update(load_from_yaml(yf))

    all_recs = []
    err = False
    for recfile in readchat:
        if not recfile.exists():
            print(f"{recfile} not found!")
            sys.exit(1)
        print(f"Parsing {recfile}...")
        err |= parse(recfile, all_recs)
    if err:
        print("Errors found. Please fix them first!")
        sys.exit(1)
    if DEBUG:
        pp = PrettyPrinter(width=160)
        pp.pprint(all_recs)

    final_routes = bake(all_recs, saved_routes)

    if saveto:
        print(f"Saving Consolidated Routes to {saveto}")
        make_backup(saveto, levels=3)
        save_to_yaml(saveto, final_routes)

    do_draw(final_routes)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
