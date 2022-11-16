# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import time
from abc import ABCMeta, abstractmethod
from math import isqrt
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

from PIL import Image, ImageDraw

from mosaic_v3.color_processing import DominantColors
from sl_maptools import MapBounds, MapCoord


class OutOfBoundsError(ValueError):
    pass


class WorldMapBuilder(metaclass=ABCMeta):
    def __init__(
        self,
        regions: Dict[MapCoord, DominantColors],
        seen_rows: Set[int],
        corner1: MapCoord,
        corner2: MapCoord,
    ):
        self.regions = regions
        self.seen_rows = seen_rows
        self.world_corner1 = corner1
        self.world_corner2 = corner2
        self._world_bounds = MapBounds.from_coords(corner1, corner2)

    @property
    def xmin(self):
        return self._world_bounds.x_leftmost

    @property
    def xmax(self):
        return self._world_bounds.x_rightmost

    @property
    def ymin(self):
        return self._world_bounds.y_bottommost

    @property
    def ymax(self):
        return self._world_bounds.y_topmost

    @property
    def width(self):
        return self._world_bounds.width

    @property
    def height(self):
        return self._world_bounds.height

    def canvas_coord(self, tile_x: int, tile_y: int, multiplier: int = 1):
        return (tile_x - self.xmin) * multiplier, (self.ymax - tile_y) * multiplier

    @abstractmethod
    def add_tile(self, coord: MapCoord, domc: DominantColors):
        raise NotImplementedError


class NightlightsMap(WorldMapBuilder):
    NightlightsTileSize = 9
    Black = 0
    White = 255

    def __init__(
        self,
        regions: Dict[MapCoord, DominantColors],
        seen_rows: Set[int],
        corner1: MapCoord,
        corner2: MapCoord,
    ):
        super().__init__(regions, seen_rows, corner1, corner2)

        canvas_box = MapCoord(self.width, self.height) * self.NightlightsTileSize
        # Need noinspection here because "LA" is actually supported but PyCharm complains
        # noinspection PyTypeChecker
        self.canvas = Image.new("LA", canvas_box)

        rect_row_black = Image.new(
            "L", (self.width * self.NightlightsTileSize, self.NightlightsTileSize), color=self.Black
        )
        for y in self.seen_rows:
            # x here MUST be 0, not x_min, because the coords here is relative to the canvas size, in pixels
            self.canvas.paste(rect_row_black, (0, self.NightlightsTileSize * (self.ymax - y)))
        self.sqw_3x3 = Image.new("L", (3, 3), color=self.White)

    def world_has_all_of(self, *items: MapCoord) -> bool:
        for i in items:
            if not self.regions.get(i):
                return False
        return True

    def world_has_none_of(self, *items: MapCoord) -> bool:
        for i in items:
            if self.regions.get(i):
                return False
        return True

    def add_tile(self, coord: MapCoord, domc: DominantColors):
        tile_sz = self.NightlightsTileSize
        black = self.Black
        white = self.White
        sqw_3x3 = self.sqw_3x3

        # region Compass points coordinates
        c_n = coord + (0, 1)
        c_e = coord + (1, 0)
        c_w = coord - (1, 0)
        c_s = coord - (0, 1)
        c_ne = coord + (1, 1)
        c_nw = coord + (-1, 1)
        c_se = coord + (1, -1)
        c_sw = coord + (-1, -1)
        # endregion

        tile_img = Image.new("L", (tile_sz, tile_sz), color=black)
        tile_img.paste(sqw_3x3, (3, 3))
        draw = ImageDraw.Draw(tile_img)

        # region Vertical & Horizontal connections
        if c_n in self.regions:
            tile_img.paste(sqw_3x3, (3, 0))
        if c_e in self.regions:
            tile_img.paste(sqw_3x3, (6, 3))
        if c_w in self.regions:
            tile_img.paste(sqw_3x3, (0, 3))
        if c_s in self.regions:
            tile_img.paste(sqw_3x3, (3, 6))
        # endregion

        # region Diagonals
        if self.world_has_all_of(c_n, c_e):
            if c_ne in self.regions:
                tile_img.paste(sqw_3x3, (6, 0))
                if self.world_has_none_of(c_s, c_sw, c_w):
                    draw.point((3, 5), fill=black)
            else:
                draw.point((6, 2), fill=white)
        if self.world_has_all_of(c_n, c_w):
            if c_nw in self.regions:
                tile_img.paste(sqw_3x3, (0, 0))
                if self.world_has_none_of(c_s, c_se, c_e):
                    draw.point((5, 5), fill=black)
            else:
                draw.point((2, 2), fill=white)
        if self.world_has_all_of(c_s, c_e):
            if c_se in self.regions:
                tile_img.paste(sqw_3x3, (6, 6))
                if self.world_has_none_of(c_n, c_nw, c_w):
                    draw.point((3, 3), fill=black)
            else:
                draw.point((6, 6), fill=white)
        if self.world_has_all_of(c_s, c_w):
            if c_sw in self.regions:
                tile_img.paste(sqw_3x3, (0, 6))
                if self.world_has_none_of(c_n, c_ne, c_e):
                    draw.point((5, 3), fill=black)
            else:
                draw.point((2, 6), fill=white)
        # endregion

        self.canvas.paste(tile_img, self.canvas_coord(*coord, tile_sz))


class MosaicMap(WorldMapBuilder):
    MosaicSubtileSize = 2

    def __init__(
        self,
        regions: Dict[MapCoord, DominantColors],
        seen_rows: Set[int],
        corner1: MapCoord,
        corner2: MapCoord,
        subtiles_domc_keys: Sequence[str],
    ):
        super().__init__(regions, seen_rows, corner1, corner2)

        self._domc_keys = subtiles_domc_keys
        # See https://docs.python.org/3/library/math.html#math.isqrt
        self._dim = 1 + isqrt(len(subtiles_domc_keys) - 1)

        canvas_box = MapCoord(self.width, self.height) * self.MosaicSubtileSize * self._dim
        self.canvas = Image.new("RGBA", canvas_box)

    def paste_subtiles(self, target: Image.Image, size: int, subtile_colors: List[Tuple[int, int, int]]):
        assert len(subtile_colors) == (size * size)
        sx, sy = 0, 0
        smax = size * self.MosaicSubtileSize
        tile_boxsz = (self.MosaicSubtileSize, self.MosaicSubtileSize)
        for color in subtile_colors:
            loc = (sx, sy)
            subtile = Image.new("RGBA", tile_boxsz, color=color)
            target.paste(subtile, loc)
            sx += self.MosaicSubtileSize
            if sx >= smax:
                sx = 0
                sy += self.MosaicSubtileSize

    def add_tile(self, coord: MapCoord, domc: DominantColors):
        tile_sz = self.MosaicSubtileSize
        tile_boxsz = MapCoord(tile_sz, tile_sz)
        tile_mosaic = Image.new("RGBA", tile_boxsz * self._dim)
        self.paste_subtiles(tile_mosaic, self._dim, domc.to_list(*self._domc_keys))
        self.canvas.paste(tile_mosaic, self.canvas_coord(*coord, tile_sz * self._dim))


def build_world_maps(
    regions: Dict[MapCoord, DominantColors],
    seen_rows: Set[int],
    nightlights_path: Path,
    mosaic_path: Path,
    corner1: MapCoord,
    corner2: MapCoord,
):
    world_bounds = MapBounds.from_coords(corner1, corner2)
    start_t = time.monotonic()

    nightlights = NightlightsMap(regions, seen_rows, corner1, corner2)
    mosaic_1x1 = MosaicMap(regions, seen_rows, corner1, corner2, DominantColors.Keys_1x1)
    mosaic_2x2 = MosaicMap(regions, seen_rows, corner1, corner2, DominantColors.Keys_2x2)
    mosaic_3x3 = MosaicMap(regions, seen_rows, corner1, corner2, DominantColors.Keys_3x3)

    count = 0
    coord: MapCoord
    domc: DominantColors
    for count, (coord, domc) in enumerate(regions.items(), start=1):
        if coord not in world_bounds:
            raise OutOfBoundsError(f"{coord} is not in {world_bounds}")

        if count % 100 == 0:
            print("|", end="", flush=True)

        nightlights.add_tile(coord, domc)
        mosaic_1x1.add_tile(coord, domc)
        mosaic_2x2.add_tile(coord, domc)
        mosaic_3x3.add_tile(coord, domc)

    elapsed_t = time.monotonic() - start_t
    print(f"{count} tiles processed in {elapsed_t:,.2f} seconds")

    print("Saving canvases ... ", end="", flush=True)
    start_t = time.monotonic()

    nightlights_path.parent.mkdir(parents=True, exist_ok=True)
    nightlights.canvas.save(nightlights_path, optimize=True)

    mosaic_path.parent.mkdir(parents=True, exist_ok=True)
    mosaic_1x1.canvas.save(mosaic_path.with_suffix(".1x1.png"), optimize=True)
    mosaic_2x2.canvas.save(mosaic_path.with_suffix(".2x2.png"), optimize=True)
    mosaic_3x3.canvas.save(mosaic_path.with_suffix(".3x3.png"), optimize=True)

    elapsed_t = time.monotonic() - start_t
    print(f"{elapsed_t:,.2f} seconds")
