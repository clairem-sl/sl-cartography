# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol, cast

from PIL import Image, ImageDraw

from analysis.recent import InterestingRegion, recent
from sl_maptools.colors import PALETTES
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions

PALETTE_NAME: Final = "blue_to_yellow"
EXISTING_COLOR: Final = 47, 47, 47


class Options(Protocol):  # noqa: D101
    size: int


def _get_options() -> Options:
    parser = argparse.ArgumentParser()

    parser.add_argument("--size", type=int, default=3)

    opts = parser.parse_args()

    return cast(Options, opts)


def main(opts: Options) -> None:  # noqa: D103
    regsdb = get_nonvoid_regions(Config.names)
    regions: set[tuple[int, int]] = {coord for coord, v in regsdb.items() if v["current_name"]}
    if bonnie_coords := get_bonnie_coords(Config.bonnie):
        regions.intersection_update(bonnie_coords)
        print(flush=True)
    del bonnie_coords

    palette = list(reversed(PALETTES[PALETTE_NAME].values()))

    db_path = Path(Config.names.dir) / Config.names.db
    interesting: list[InterestingRegion] = sorted(recent(db_path, (len(palette) - 1) * 2))

    for one in interesting:
        regions.discard(one.coord)

    psize = 2100 * opts.size
    canvas = Image.new("RGB", (psize, psize), color=(0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGB")

    print("Drawing older regions...", end="", flush=True)
    for i, coord in enumerate(regions):
        if (i % 1000) == 0:
            print(".", end="", flush=True)
        x, y = coord
        cx = x * opts.size
        cy = (2099 - y) * opts.size
        draw.rectangle((cx, cy, cx + opts.size, cy + opts.size), fill=EXISTING_COLOR)
    print()

    print("Drawing recent regions...", end="", flush=True)
    nao = datetime.now().astimezone()
    for one in interesting:
        print(".", end="", flush=True)
        age = (nao - one.timestamp).days
        color = palette[age // 2]
        x, y = one.coord
        cx = x * opts.size
        cy = (2099 - y) * opts.size
        draw.rectangle((cx, cy, cx + opts.size, cy + opts.size), fill=color)
    print()

    targ = Path(Config.nightlights.dir) / "recent.png"
    canvas.save(targ, optimize=True)
    print(f"Saved to {targ}")


if __name__ == "__main__":
    main(_get_options())
