# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
from pathlib import Path
from typing import Final, Protocol, cast

from PIL import Image, ImageFont

from cartographer_v4.grid import make_grid, TextSettings
from sl_maptools import CoordType, RegionsDBRecord3
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords

RGBATuple = tuple[int, int, int, int]


Config: SLMapToolsConfig = ConfigReader("config.toml")

DB_PATH: Final[Path] = Path(Config.names.dir) / Config.names.db
AREAMAPS_DIR: Final[Path] = Path(Config.areas.dir)

FONT_NAME: Final[Path] = Path(Config.grids.font_name)
FONT_TEXT_SIZE: Final[int] = 16
FONT_COORD: Final[Path] = Path(Config.grids.font_coord)
FONT_COORD_SIZE: Final[int] = 12
TEXT_RGBA: Final[RGBATuple] = (255, 255, 255, 191)
STROKE_WIDTH_NAME: Final[int] = 2
STROKE_WIDTH_COORD: Final[int] = 2
STROKE_RGBA: Final[RGBATuple] = (0, 0, 0, 191)


ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 32)


class GridOptions(Protocol):
    no_names: bool
    no_coords: bool
    areas: list[str]


def get_options() -> GridOptions:
    parser = argparse.ArgumentParser("cartographer_v4.grid")

    parser.add_argument("--no-names", action="store_true", help="Don't add region names to the grid")
    parser.add_argument("--no-coords", action="store_true", help="Don't add coordinates to the grid")
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

    font_text = ImageFont.truetype(str(FONT_NAME), FONT_TEXT_SIZE)
    # w, h = font.getsize("M", stroke_width=STROKE_WIDTH)
    # h_offs = 256 - 3 - h
    font_coord = ImageFont.truetype(str(FONT_COORD), FONT_COORD_SIZE)

    validation_set: set[CoordType] = set()
    with DB_PATH.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)
    validation_set.update(k for k, v in regsdb.items() if v["current_name"])
    bonnie_coords = get_bonnie_coords(None, True)
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

    regname_settings: TextSettings = {
        "font": font_text,
        "fill": TEXT_RGBA,
        "stroke_width": STROKE_WIDTH_NAME,
        "stroke_fill": STROKE_RGBA,
    }
    coord_settings: TextSettings = {
        "font": font_coord,
        "fill": TEXT_RGBA,
        "stroke_width": STROKE_WIDTH_NAME,
        "stroke_fill": STROKE_RGBA,
    }

    tot = len(want_areas)
    for num, areamap in enumerate(want_areas, start=1):
        print(f"\n({num}/{tot}) {areamap.stem}", flush=True)
        make_grid(
            areamap,
            regsdb,
            grid_overlay_dir,
            validation_set,
            regname_settings,
            coord_settings,
            opts.no_names,
            opts.no_coords
        )

    print()


if __name__ == "__main__":
    options = get_options()
    main(options)
