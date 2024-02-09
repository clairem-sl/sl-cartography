# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

from PIL import Image, ImageDraw

# noinspection PyUnresolvedReferences
from PIL.Image import Resampling

from sl_maptools import inventorize_maps_latest
from sl_maptools.config import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords

if TYPE_CHECKING:
    from sl_maptools import CoordType

RGBTuple = tuple[int, int, int]
RGBATuple = tuple[int, int, int, int]


Config: SLMapToolsConfig = ConfigReader("config.toml")

MAP_DIR: Final[Path] = Path(Config.maps.dir)
GRID_DIR: Final[Path] = Path(Config.gridsectors.dir)

# fmt: off
GRID_COLS: Final[list[str]] = [
    "AA", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U"
]
# fmt: on

ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 64, 32)

DEFA_TILE_SZ: Final[int] = 64
DEFA_BG_COLOR: Final[RGBTuple] = 0, 0, 0
DEFA_GRID_CLR: Final[RGBTuple] = 255, 255, 255


class Options(Protocol):
    """Represents options extracted from CLI"""

    tile_size: int
    bg_color: RGBTuple
    grid_color: RGBTuple


class RGBParser(argparse.Action):
    """Parses comma-separated RGB values into a 3-tuple"""

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: D102, ANN001, ARG002
        if (m := re.match(r"^(?P<r>\d{1,3}),(?P<g>\d{1,3}),(?P<b>\d{1,3})$", values)) is None:
            parser.error("Please enter color in r,g,b format!")
        rgb = tuple(map(int, m.groups()))
        if not all(0 <= i <= 255 for i in rgb):  # noqa: PLR2004
            parser.error("Each r,g,b must be 0 <= value <= 255!")
        setattr(namespace, self.dest, rgb)


def get_options() -> Options:
    """Extract options from CLI"""
    parser = argparse.ArgumentParser("worldmap_v4.gridsectors")

    parser.add_argument("--tile-size", type=int, default=DEFA_TILE_SZ)
    parser.add_argument(
        "--bg-color", action=RGBParser, default=DEFA_BG_COLOR, help="Background color in r,g,b (no spaces)"
    )
    parser.add_argument(
        "--grid-color", action=RGBParser, default=DEFA_GRID_CLR, help="Grid color in r,g,b (no spaces)"
    )

    _opts = parser.parse_args()
    return cast(Options, _opts)


def main(opts: Options) -> None:  # noqa: D103
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    valid_coords = get_bonnie_coords(Config.bonnie)
    maptiles = {co: mapp for co, mapp in inventorize_maps_latest(MAP_DIR).items() if co in valid_coords}
    bk_clr = (*opts.bg_color, 0)

    sq_sz = opts.tile_size * 10
    sq = Image.new("RGBA", (sq_sz, sq_sz), color=bk_clr)
    sq_draw = ImageDraw.Draw(sq)
    ul = 0
    lr = sq_sz - 1
    for a in ALPHA_PATTERN:
        sq_draw.rectangle((ul, ul, lr, lr), width=1, outline=(*opts.grid_color, a))
        ul += 1
        lr -= 1

    gridsec_sz = sq_sz * 10
    gridsec_box = gridsec_sz, gridsec_sz
    gridsec_overlay = Image.new("RGBA", gridsec_box, color=bk_clr)
    for cx in range(0, gridsec_sz, sq_sz):
        for cy in range(0, gridsec_sz, sq_sz):
            gridsec_overlay.paste(sq, (cx, cy))

    tile_box = opts.tile_size, opts.tile_size
    for col, col_letter in enumerate(GRID_COLS):
        for row, _ in enumerate(GRID_COLS):
            print(f"{col_letter}{row} ...", end="", flush=True)
            grid_tiles: dict[CoordType, Path] = {}
            for y in range(row * 100, (row + 1) * 100):
                for x in range(col * 100, (col + 1) * 100):
                    co = x, y
                    if co in maptiles:
                        grid_tiles[co] = maptiles[co]
            if len(grid_tiles) == 0:
                print(" no regions")
                continue
            print(f" {len(grid_tiles)} ...", end="", flush=True)
            gridsector_mapp = GRID_DIR / f"{col_letter}{row}.png"
            if not gridsector_mapp.exists():
                grid_canvas = Image.new("RGBA", gridsec_box, color=bk_clr)
                for co, mapp in grid_tiles.items():
                    x, y = co
                    cx = (x - (col * 100)) * opts.tile_size
                    cy = (99 - (y - (row * 100))) * opts.tile_size
                    with Image.open(mapp) as immap:
                        immap.thumbnail(tile_box, resample=Resampling.LANCZOS)
                        grid_canvas.paste(immap, (cx, cy))
                out = Image.alpha_composite(grid_canvas, gridsec_overlay)
                out.save(gridsector_mapp)
                print(" 💾 ", end="", flush=True)
            print(f"{gridsector_mapp}")


if __name__ == "__main__":
    main(get_options())
