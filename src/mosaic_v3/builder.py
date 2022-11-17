# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import time
from abc import ABCMeta, abstractmethod
from math import isqrt
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from PIL import Image, ImageDraw

from mosaic_v3.color_processing import DominantColors
from sl_maptools import MapBounds, MapCoord


class OutOfBoundsError(ValueError):
    """Raised if a coordinate falls outside the map's boundaries"""

    pass


class WorldMapBuilder(metaclass=ABCMeta):
    def __init__(
        self,
        regions: Dict[MapCoord, DominantColors],
        seen_rows: Set[int] | None,
        corner1: MapCoord,
        corner2: MapCoord,
    ):
        self.regions = regions
        self.seen_rows = seen_rows
        self.world_corner1 = corner1
        self.world_corner2 = corner2
        self._world_bounds = MapBounds.from_coords(corner1, corner2)
        self.canvas: Optional[Image.Image] = None

    @property
    def xmin(self) -> int:
        return self._world_bounds.x_leftmost

    @property
    def xmax(self) -> int:
        return self._world_bounds.x_rightmost

    @property
    def ymin(self) -> int:
        return self._world_bounds.y_bottommost

    @property
    def ymax(self) -> int:
        return self._world_bounds.y_topmost

    @property
    def width(self) -> int:
        return self._world_bounds.width

    @property
    def height(self) -> int:
        return self._world_bounds.height

    def canvas_coord(self, tile_x: int, tile_y: int, multiplier: int = 1) -> tuple[int, int]:
        return (tile_x - self.xmin) * multiplier, (self.ymax - tile_y) * multiplier

    @abstractmethod
    def add_tile(self, coord: MapCoord, domc: DominantColors) -> None:
        raise NotImplementedError

    @staticmethod
    def box(value: int) -> Tuple[int, int]:
        return value, value


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

        self.subtile_sz = self.NightlightsTileSize // 3
        if self.subtile_sz * 3 != self.NightlightsTileSize:
            raise ValueError("NightlightsTileSize must be an integer multiple of 3!")

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

        self.subtile_w = Image.new("L", (self.subtile_sz, self.subtile_sz), color=self.White)

    def world_has_all_of(self, *coords: MapCoord) -> bool:
        return all(map(self.regions.__contains__, coords))

    def world_has_none_of(self, *coords: MapCoord) -> bool:
        return not any(map(self.regions.__contains__, coords))

    def add_tile(self, coord: MapCoord, domc: DominantColors) -> None:
        tile_sz = self.NightlightsTileSize
        subtile_sz = self.subtile_sz
        black = self.Black
        white = self.White
        subtile_w = self.subtile_w

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
        tile_img.paste(subtile_w, (subtile_sz, subtile_sz))
        draw = ImageDraw.Draw(tile_img)

        # region Vertical & Horizontal connections
        if c_n in self.regions:
            tile_img.paste(subtile_w, (subtile_sz, 0))
        if c_e in self.regions:
            tile_img.paste(subtile_w, (subtile_sz * 2, subtile_sz))
        if c_w in self.regions:
            tile_img.paste(subtile_w, (0, subtile_sz))
        if c_s in self.regions:
            tile_img.paste(subtile_w, (subtile_sz, subtile_sz * 2))
        # endregion

        # region Diagonals
        if self.world_has_all_of(c_n, c_e):
            if c_ne in self.regions:
                tile_img.paste(subtile_w, (subtile_sz * 2, 0))
                if self.world_has_none_of(c_s, c_sw, c_w):
                    draw.point((subtile_sz, subtile_sz * 2 - 1), fill=black)
            else:
                draw.point((subtile_sz * 2, subtile_sz - 1), fill=white)

        if self.world_has_all_of(c_n, c_w):
            if c_nw in self.regions:
                tile_img.paste(subtile_w, (0, 0))
                if self.world_has_none_of(c_s, c_se, c_e):
                    draw.point(self.box(subtile_sz * 2 - 1), fill=black)
            else:
                draw.point(self.box(subtile_sz - 1), fill=white)

        if self.world_has_all_of(c_s, c_e):
            if c_se in self.regions:
                tile_img.paste(subtile_w, self.box(subtile_sz * 2))
                if self.world_has_none_of(c_n, c_nw, c_w):
                    draw.point((subtile_sz, subtile_sz), fill=black)
            else:
                draw.point(self.box(subtile_sz * 2), fill=white)

        if self.world_has_all_of(c_s, c_w):
            if c_sw in self.regions:
                tile_img.paste(subtile_w, (0, subtile_sz * 2))
                if self.world_has_none_of(c_n, c_ne, c_e):
                    draw.point((subtile_sz * 2 - 1, subtile_sz), fill=black)
            else:
                draw.point((subtile_sz - 1, subtile_sz * 2), fill=white)

        # endregion

        self.canvas.paste(tile_img, self.canvas_coord(*coord, tile_sz))


class MosaicMap(WorldMapBuilder):
    MosaicSubtileSize = 2

    def __init__(
        self,
        regions: Dict[MapCoord, DominantColors],
        corner1: MapCoord,
        corner2: MapCoord,
        subtiles_domc_keys: Sequence[str],
    ):
        """
        :param regions: A dict of MapCoord:DominantColors to build the map upon
        :param corner1: Coordinates for one corner of the map
        :param corner2: Coordinates for the corner of the map opposite to corner 1
        :param subtiles_domc_keys: A sequence of keys with which to color the subtiles.
        These are defined as class attributes in DominantColors
        """
        super().__init__(regions, None, corner1, corner2)

        self._domc_keys = subtiles_domc_keys
        # See https://docs.python.org/3/library/math.html#math.isqrt
        self._dim = 1 + isqrt(len(subtiles_domc_keys) - 1)

        canvas_box = MapCoord(self.width, self.height) * self.MosaicSubtileSize * self._dim
        self.canvas = Image.new("RGBA", canvas_box)

    def paste_subtiles(self, tile: Image.Image, dimension: int, subtile_colors: List[Tuple[int, int, int]]) -> None:
        """
        Pastes subtiles (squares of certain colors) into the tile image.

        :param tile: The tile to which the subtiles will be pasted
        :param dimension: The dimension of the tile (in units of subtiles)
        :param subtile_colors: The colors of the subtiles. The number of colors given must match the actual number of
        subtiles to be pasted to the tile.
        :return: None
        :raises AttributeError: if the number of colors is not equal to total number of subtiles
        """
        if len(subtile_colors) != (dimension * dimension):
            raise AttributeError("Number of colors must match total number of subtiles!")
        sx, sy = 0, 0
        smax = dimension * self.MosaicSubtileSize
        subtile_boxsz = (self.MosaicSubtileSize, self.MosaicSubtileSize)
        for color in subtile_colors:
            loc = (sx, sy)
            subtile = Image.new("RGB", subtile_boxsz, color=color)
            tile.paste(subtile, loc)
            sx += self.MosaicSubtileSize
            if sx >= smax:
                sx = 0
                sy += self.MosaicSubtileSize

    def add_tile(self, coord: MapCoord, domc: DominantColors) -> None:
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
    ignore_out_of_bounds: bool = False,
) -> None:
    """
    Generates the world map images.

    Currently hardcoded to produce 4 kinds of world maps.

    :param regions: A dict of MapCoord:DominantColors to build the world maps with
    :param seen_rows: A set of rownumbers indicating which rows have been fully-fetched
    :param nightlights_path: Path for saving nightlights map
    :param mosaic_path: Path for saving mosaic map; will be transformed into several paths
    :param corner1: Coordinates of a corner of the world map
    :param corner2: Coordinates of another corner of the world map, opposite corner 1
    :param ignore_out_of_bounds: If False (default) will raise an exception if regions contain a coordinate that
    falls outside the bounds of the world map
    :return: None
    :raises OutOfBoundsError: if a coordinat in regions fall outside map bounds, but only if ignore_out_of_bounds is
    set to False
    """
    world_bounds = MapBounds.from_coords(corner1, corner2)
    start_t = time.monotonic()

    nightlights = NightlightsMap(regions, seen_rows, corner1, corner2)
    mosaic_1x1 = MosaicMap(regions, corner1, corner2, DominantColors.Keys_1x1)
    mosaic_2x2 = MosaicMap(regions, corner1, corner2, DominantColors.Keys_2x2)
    mosaic_3x3 = MosaicMap(regions, corner1, corner2, DominantColors.Keys_3x3)

    count = 0
    coord: MapCoord
    domc: DominantColors
    for count, (coord, domc) in enumerate(regions.items(), start=1):
        if coord not in world_bounds:
            if not ignore_out_of_bounds:
                raise OutOfBoundsError(f"{coord} is not in {world_bounds}")
            # Ignore silently
            continue

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
