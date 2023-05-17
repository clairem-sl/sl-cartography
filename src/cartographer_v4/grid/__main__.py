# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
from pathlib import Path
from typing import Final, Protocol, cast

from PIL import Image, ImageDraw, ImageFont

from sl_maptools import CoordType, RegionsDBRecord
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords

RGBATuple = tuple[int, int, int, int]


Config: SLMapToolsConfig = ConfigReader("config.toml")

DB_PATH: Final[Path] = Path(Config.names.dir) / Config.names.db
AREAMAPS_DIR: Final[Path] = Path(Config.areas.dir)

FONT_PATH: Final[Path] = Path(Config.grids.font_name)
FONT_SIZE: Final[int] = int(Config.grids.font_size)
TEXT_RGBA: Final[RGBATuple] = (255, 255, 255, 255)
STROKE_WIDTH: Final[int] = 2
STROKE_RGBA: Final[RGBATuple] = (0, 0, 0, 255)


ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 32)


class GridOptions(Protocol):
    areas: list[str]


def get_options() -> GridOptions:
    parser = argparse.ArgumentParser("cartographer_v4.grid")

    parser.add_argument(
        "--areas",
        metavar="AREA_LIST",
        type=str,
        nargs="+",
        help=(
            "Space- and/or comma-separated list of areas to retrieve, in addition to prior progress. "
            "If this option is specified, then make grid for listed areas ONLY."
        )
    )

    _opts = parser.parse_args()
    return cast(GridOptions, _opts)


def main(opts: GridOptions):
    # Disable DecompressionBombWarning
    Image.MAX_IMAGE_PIXELS = None

    areamaps_dir = Path(Config.areas.dir)
    grid_composite_dir = Path(Config.grids.dir_composite)
    grid_composite_dir.mkdir(exist_ok=True)
    grid_overlay_dir = Path(Config.grids.dir_overlay)
    grid_overlay_dir.mkdir(exist_ok=True)

    sq = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
    sq_draw = ImageDraw.Draw(sq)

    ul = 0
    lr = 255
    for a in ALPHA_PATTERN:
        sq_draw.rectangle((ul, ul, lr, lr), width=1, outline=(255, 255, 255, a))
        ul += 1
        lr -= 1

    font = ImageFont.truetype(str(FONT_PATH), FONT_SIZE)
    # w, h = font.getsize("M", stroke_width=STROKE_WIDTH)
    # h_offs = 256 - 3 - h

    validation_set: set[CoordType] = set()
    with DB_PATH.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord] = pickle.load(fin)
    validation_set.update(k for k, v in regsdb.items() if v["current_name"])
    bonnie_coords = get_bonnie_coords(None, True)
    print()
    validation_set.intersection_update(bonnie_coords)

    want_areas: set[Path]
    if opts.areas:
        cs_anames = {k.casefold(): k for k in KNOWN_AREAS.keys()}
        want_areas = {
            (areamaps_dir / cs_anames[a1]).with_suffix(".png")
            for area in opts.areas
            for a1 in map(str.casefold, area.split(","))
            if a1 in cs_anames
        }
    else:
        want_areas = {
            areamap
            for areamap in areamaps_dir.glob("*.png")
        }

    for areamap in want_areas:
        print(f"{areamap}", end="", flush=True)
        areaname = areamap.stem

        overlay_p = grid_overlay_dir / (areaname + ".overlay.png")
        gridc = None
        if not overlay_p.exists():
            bounds = KNOWN_AREAS[areaname]
            x1, y1, x2, y2 = bounds
            size_x = (x2 - x1 + 1) * 256
            size_y = (y2 - y1 + 1) * 256
            gridc = Image.new("RGBA", (size_x, size_y), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(gridc)
            for i, xy in enumerate(bounds.xy_iterator(), start=1):
                if xy not in validation_set:
                    continue
                x, y = xy
                cx = (x - x1) * 256
                cy = (y2 - y) * 256
                gridc.paste(sq, (cx, cy))
                regname = regsdb[xy]["current_name"]
                # print(regname)
                draw.text(
                    (cx + 5, cy + 4),
                    regname,
                    font=font,
                    fill=TEXT_RGBA,
                    stroke_width=STROKE_WIDTH,
                    stroke_fill=STROKE_RGBA,
                )
                if (i % 10) == 0:
                    print(".", end="", flush=True)

            gridc.save(overlay_p)
        print(f"\n  => {overlay_p}", end="", flush=True)
        composite_p = grid_composite_dir / (areaname + ".gridded.png")
        if gridc:
            if not composite_p.exists():
                with Image.open(areamap) as img:
                    out = Image.alpha_composite(img, gridc)
                    out.save(composite_p)
        if composite_p.exists():
            print(f"\n  => {composite_p}", flush=True)


if __name__ == "__main__":
    options = get_options()
    main(options)
