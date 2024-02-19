# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast

from PIL import Image, ImageDraw

from sl_maptools import COORD_RANGE, MapCoord, inventorize_maps_all
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.utils import make_backup
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions

TilerClass: type | None = None

MIN_X: Final[int] = COORD_RANGE.min_
MAX_X: Final[int] = COORD_RANGE.max_

MIN_Y: Final[int] = COORD_RANGE.min_
MAX_Y: Final[int] = COORD_RANGE.max_


# csize  = The edge-length of the center square
# border = The width of the gap around the center square
# shrink = How many pixels to reduce to draw the connecting paths
#          That means, the connecting paths' width will be ( csize - 2 * shrink )

TILERS: Final[dict[str, dict[str, int]]] = {
    "b42": {"csize": 4, "border": 2, "shrink": 1},
    "b43": {"csize": 4, "border": 3, "shrink": 1},
    "b52": {"csize": 5, "border": 2, "shrink": 1},
    "b53": {"csize": 5, "border": 3, "shrink": 1},
    "s33": {"csize": 3, "border": 3, "shrink": 0},
    "s22": {"csize": 2, "border": 2, "shrink": 0},
}


class Options(Protocol):
    """Options returned from command line"""

    no_bonnie: bool
    no_maptiles: bool
    tiler: str


class BonnieRegionData(TypedDict):
    """Relevant data extracted from BonnieBots DB"""

    region_name: str
    region_x: int
    region_y: int


def _get_options() -> Options:
    """Get options from command line"""
    parser = argparse.ArgumentParser("worldmap_v4.nightlights")

    parser.add_argument("--no-bonnie", action="store_true", default=False, help="Don't validate against BonnieBots DB")
    parser.add_argument(
        "--no-maptiles", action="store_true", default=False, help="Don't validate against MapTiles collection"
    )

    parser.add_argument("--tiler", default="b52", choices=TILERS.keys())

    _opts = parser.parse_args()

    return cast(Options, _opts)


class TileProducer:
    """
    Draws a tile parametrically
    """

    __slots__ = (
        "regions",
        "size",
        "_center",
        "_roundedcorners",
        "_elbows",
        "_bridges",
        "_diagonals",
        "_round",
        "_elbow",
    )

    _Neighbors: Final[dict[tuple[int, int], str]] = {
        (0, -1): "S",
        (-1, 0): "W",
        (1, 0): "E",
        (0, 1): "N",
        (1, 1): "NE",
        (-1, -1): "SW",
        (1, -1): "SE",
        (-1, 1): "NW",
    }

    def __init__(self, regions: set[MapCoord], *, csize: int, border: int, shrink: int):
        """
        aaa

        :param regions: Set of MapCoord's to make a Nightlights Map from
        :param csize: Center (bead) size
        :param border: Border between edge of tile to center
        :param shrink: How much narrower bridges are compared to center
        """
        if not regions:
            raise ValueError("Empty regionset")
        if csize < 1:
            raise ValueError("csize must be at least 1")
        if border < 1:
            raise ValueError("border must be at least 1")
        if shrink < 0:
            raise ValueError("shrink must be at least 0")
        if csize <= shrink * 2:
            raise ValueError("shrink too large")
        self.regions = regions
        self.size = csize + border * 2
        sz1 = self.size - 1
        x1 = y1 = border
        x2 = y2 = sz1 - border
        self._center = x1, y1, x2, y2
        self._roundedcorners = {
            "NW": (x2, y2),
            "NE": (x1, y2),
            "SW": (x2, y1),
            "SE": (x1, y1),
        }
        x11 = x1 - 1
        y11 = y1 - 1
        x21 = x2 + 1
        y21 = y2 + 1
        self._elbows = {
            "NW": (x11, y11),
            "NE": (x21, y11),
            "SW": (x11, y21),
            "SE": (x21, y21),
        }
        self._bridges = {
            "N": (x1 + shrink, 0, x2 - shrink, y11),
            "S": (x1 + shrink, y2, x2 - shrink, sz1),
            "W": (0, y1 + shrink, x11, y2 - shrink),
            "E": (x21, y1 + shrink, sz1, y2 - shrink),
        }
        ax1 = x11 + shrink
        ay1 = y11 + shrink
        ax2 = x21 - shrink
        ay2 = y21 - shrink
        self._diagonals = {
            "NW": (0, 0, ax1, ay1),
            "NE": (ax2, 0, sz1, ay1),
            "SW": (0, ay2, ax1, sz1),
            "SE": (ax2, ay2, sz1, sz1),
        }
        self._round = True
        self._elbow = False

    def get_neighbors(self, coord: MapCoord) -> set[str]:
        """
        Get existing neighbors of a region at (x, y)

        :param coord: Geo-coordinate of the region
        :return: A set of compass points representing existing neighbors
        """
        return {compass for offset, compass in self.__class__._Neighbors.items() if (coord + offset) in self.regions}

    def maketile(self, coord: MapCoord) -> Image:
        """
        Makes a tile of the region at (x, y) considering its neighbors
        """
        tile = Image.new("L", (self.size, self.size))
        draw = ImageDraw.Draw(tile)
        draw.rectangle(self._center, fill=255)

        if not (neighs := self.get_neighbors(coord)):
            return tile

        for compass, box in self._bridges.items():
            if compass in neighs:
                draw.rectangle(box, fill=255)
        for compass, box in self._diagonals.items():
            cs = set(compass)
            if self._elbow and compass not in neighs and cs.issubset(neighs):
                point = self._elbows[compass]
                draw.point(point, fill=255)
            cs.add(compass)
            if cs.issubset(neighs):
                draw.rectangle(box, fill=255)
            if self._round and cs == neighs:
                point = self._roundedcorners[compass]
                draw.point(point, fill=0)
        return tile


def canvas_coord(region_x: int, region_y: int, multiplier: int = 1) -> tuple[int, int]:
    """
    Converts geo-coords (in units of Regions) to canvas coords (in units of pixels)

    This is not a simple multiplied-items tuple like what's implemented by MapCoord.__mul__

    This method implements the shift, reflect, and multiplication necessary to do the conversion.

    :param region_x: X geo-coordinate of the Region
    :param region_y: Y geo-coordinate of the Region
    :param multiplier: Optional multiplier
    :return: The canvas coordinate for the Region
    """
    return (region_x - MIN_X) * multiplier, (MAX_Y - region_y) * multiplier


def make_nightlights2(regions: set[MapCoord], *, tiler: str) -> Image.Image:
    """
    Actually create the Nightlights map, given a set of coordinates and a tiler class

    :param regions: Set of regions which we will map
    :param tiler: The class to be used to create the actual map
    :return: A completed map
    """
    width = MAX_X - MIN_X + 1
    height = MAX_Y - MIN_Y + 1

    producer = TileProducer(regions, **TILERS[tiler])

    region_size = producer.size
    canvas_box = cast(tuple[int, int], MapCoord(width, height) * region_size)
    canvas = Image.new("L", canvas_box, color=0)

    for coord in regions:
        region_img = producer.maketile(coord)
        canvas.paste(region_img, canvas_coord(*coord, region_size))

    return canvas


def main(opts: Options) -> None:  # noqa: D103
    regsdb = get_nonvoid_regions(Config.names)
    regions: set[tuple[int, int]] = set(coord for coord, v in regsdb.items() if v["current_name"])

    # Filter with Bonnie if not prevented
    if not opts.no_bonnie:
        # Get Bonnie data
        bonnie_coords = get_bonnie_coords(Config.bonnie)
        if bonnie_coords:
            regions.intersection_update(bonnie_coords)
            print(flush=True)
        del bonnie_coords

    # Filter with Maptiles if not prevented
    if not opts.no_maptiles:
        # Get Maptiles data
        mapfiles = inventorize_maps_all(Config.maps.dir)
        regions.intersection_update(mapfiles.keys())
        del mapfiles

    targ = (
        Path(Config.nightlights.dir)
        / f"worldmap4_nightlights_{opts.tiler}_{datetime.now().astimezone():%y%m%d-%H%M}.png"
    )
    if targ.exists():
        make_backup(targ)
        targ.unlink()

    print("Creating Nightlights Map ... ", end="", flush=True)
    canvas = make_nightlights2({MapCoord(x, y) for x, y in regions}, tiler=opts.tiler)

    print("\nSaving nightlights map ... ", end="", flush=True)
    targ.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(targ, optimize=True)

    print(f"\nNightlights mosaic saved to {targ}")


if __name__ == "__main__":
    main(_get_options())
