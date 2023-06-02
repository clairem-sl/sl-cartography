# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
from pathlib import Path
from typing import Final, Protocol, cast

from PIL import Image, ImageDraw, ImageFont
# noinspection PyUnresolvedReferences
from PIL.Image import Resampling

from sl_maptools import COORD_RANGE, CoordType, RegionsDBRecord, AreaBounds
from sl_maptools.knowns import KNOWN_AREAS, SUPPRESS_FOR_AREAS
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords, inventorize_maps_latest

RGBATuple = tuple[int, int, int, int]

Config: SLMapToolsConfig = ConfigReader("config.toml")

MAP_DIR: Final[Path] = Path(Config.maps.dir)
GRID_DIR: Final[Path] = Path(r"C:\Cache\SL-Carto\WorldMaps\GridSectors")


GRID_COLS: Final[list[str]] = [
    "AA", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U"
]

ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 64, 32)


def main():
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    valid_coords = get_bonnie_coords(None, True)
    maptiles = {
        co: mapp
        for co, mapp in inventorize_maps_latest(MAP_DIR).items()
        if co in valid_coords
    }

    sq = Image.new("RGBA", (640, 640), color=(0, 0, 0, 0))
    sq_draw = ImageDraw.Draw(sq)
    ul = 0
    lr = 639
    for a in ALPHA_PATTERN:
        sq_draw.rectangle((ul, ul, lr, lr), width=1, outline=(255, 255, 255, a))
        ul += 1
        lr -= 1
    gridsec_overlay = Image.new("RGBA", (6400, 6400), color=(0, 0, 0, 0))
    for cx in range(0, 6400, 640):
        for cy in range(0, 6400, 640):
            gridsec_overlay.paste(sq, (cx, cy))

    for col, col_letter in enumerate(GRID_COLS):
        for row in range(0, 22):
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
                grid_canvas = Image.new("RGBA", (6400, 6400), color=(0, 0, 0, 0))
                for co, mapp in grid_tiles.items():
                    x, y = co
                    cx = (x - (col * 100)) * 64
                    cy = (99 - (y - (row * 100))) * 64
                    with Image.open(mapp) as immap:
                        immap.thumbnail((64, 64), resample=Resampling.LANCZOS)
                        grid_canvas.paste(immap, (cx, cy))
                    out = Image.alpha_composite(grid_canvas, gridsec_overlay)
                    out.save(gridsector_mapp)
                    print(f" 💾 ", end="", flush=True)
            print(f"{gridsector_mapp}")


if __name__ == '__main__':
    main()
