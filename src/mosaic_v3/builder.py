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
from sl_maptools import AreaBounds, MapCoord


class OutOfBoundsError(ValueError):
    """Raised if a coordinate falls outside the map's boundaries"""

    pass


class WorldMapBuilder(metaclass=ABCMeta):
    """
    Abstract class that provides the common protocol for map builders
    """

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
        self._world_bounds = AreaBounds.from_coords(corner1, corner2)
        self.canvas: Optional[Image.Image] = None

    @property
    def xmin(self) -> int:
        return self._world_bounds.x_westmost

    @property
    def xmax(self) -> int:
        return self._world_bounds.x_eastmost

    @property
    def ymin(self) -> int:
        return self._world_bounds.y_southmost

    @property
    def ymax(self) -> int:
        return self._world_bounds.y_northmost

    @property
    def width(self) -> int:
        return self._world_bounds.width

    @property
    def height(self) -> int:
        return self._world_bounds.height

    def canvas_coord(self, region_x: int, region_y: int, multiplier: int = 1) -> tuple[int, int]:
        """
        Converts geo-coords (in units of Regions) to canvas coords (in units of pixels)

        This is not a simple multiplied-items tuple like what's implemented by MapCoord.__mul__

        This method implements the shift, reflect, and multiplication necessary to do the conversion.

        :param region_x: X geo-coordinate of the Region
        :param region_y: Y geo-coordinate of the Region
        :param multiplier: Optional multiplier
        :return: The canvas coordinate for the Region
        """
        return (region_x - self.xmin) * multiplier, (self.ymax - region_y) * multiplier

    @abstractmethod
    def add_region(self, coord: MapCoord, domc: DominantColors) -> None:
        """
        Adds a Region into the world map.

        :param coord: Coordinate of the Region
        :param domc: Dominant colors of the Region
        :return: None
        """
        raise NotImplementedError

    def save(self, target: Path, optimize: bool = True) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        self.canvas.save(target, optimize=optimize)
        return target

    @staticmethod
    def box(value: int) -> Tuple[int, int]:
        return value, value


class NightlightsMap(WorldMapBuilder):
    """
    Builds a 'nightlights' map Region-by-Region.
    """

    NightlightsRegionSize = 9
    """Size of each region in the Nightlights map, in units of pixels"""
    Black = 0
    """Definition of 'black' color. You will need to ensure the data format is suitable for the image type."""
    White = 255
    """Definition of 'white' color. You will need to ensure the data format is suitable for the image type."""

    def __init__(
        self,
        regions: Dict[MapCoord, DominantColors],
        seen_rows: Set[int],
        corner1: MapCoord,
        corner2: MapCoord,
    ):
        """
        :param regions: A dict of coordinates and region_data (the latter will be ignored)
        :param seen_rows: A set of rows known to have been fully-fetched
        :param corner1: Coordinates for one corner of the map
        :param corner2: Coordinates for the corner of the map opposite to corner 1
        :raises ValueError: if the NightlightsRegionSize class attribute is not a multiple of 3
        """
        super().__init__(regions, seen_rows, corner1, corner2)

        self.slab_sz = self.NightlightsRegionSize // 3
        if self.slab_sz * 3 != self.NightlightsRegionSize:
            raise ValueError("NightlightsRegionSize must be an integer multiple of 3!")

        canvas_box = MapCoord(self.width, self.height) * self.NightlightsRegionSize
        # Need 'noinspection' here because "LA" is actually supported but PyCharm complains
        # noinspection PyTypeChecker
        self.canvas = Image.new("LA", canvas_box)

        rect_row_black = Image.new(
            "L", (self.width * self.NightlightsRegionSize, self.NightlightsRegionSize), color=self.Black
        )
        for y in self.seen_rows:
            # x here MUST be 0, not x_min, because the coords here is relative to the canvas size, in pixels
            self.canvas.paste(rect_row_black, (0, self.NightlightsRegionSize * (self.ymax - y)))

        self.slab_w = Image.new("L", (self.slab_sz, self.slab_sz), color=self.White)

    def world_has_all_of(self, *coords: MapCoord) -> bool:
        return all(map(self.regions.__contains__, coords))

    def world_has_none_of(self, *coords: MapCoord) -> bool:
        return not any(map(self.regions.__contains__, coords))

    def add_region(self, coord: MapCoord, domc: DominantColors) -> None:
        """
        Adds a Region into the world map.

        The domc parameter will be ignored.

        :param coord: Coordinate of the Region
        :param domc: Ignored
        :return: None
        """
        region_sz = self.NightlightsRegionSize
        slab_sz = self.slab_sz
        black = self.Black
        white = self.White
        slab_w = self.slab_w

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

        region_img = Image.new("L", (region_sz, region_sz), color=black)
        region_img.paste(slab_w, (slab_sz, slab_sz))
        draw = ImageDraw.Draw(region_img)

        # region Vertical & Horizontal connections
        if c_n in self.regions:
            region_img.paste(slab_w, (slab_sz, 0))
        if c_e in self.regions:
            region_img.paste(slab_w, (slab_sz * 2, slab_sz))
        if c_w in self.regions:
            region_img.paste(slab_w, (0, slab_sz))
        if c_s in self.regions:
            region_img.paste(slab_w, (slab_sz, slab_sz * 2))
        # endregion

        # region Diagonals
        if self.world_has_all_of(c_n, c_e):
            if c_ne in self.regions:
                region_img.paste(slab_w, (slab_sz * 2, 0))
                if self.world_has_none_of(c_s, c_sw, c_w):
                    draw.point((slab_sz, slab_sz * 2 - 1), fill=black)
            else:
                draw.point((slab_sz * 2, slab_sz - 1), fill=white)

        if self.world_has_all_of(c_n, c_w):
            if c_nw in self.regions:
                region_img.paste(slab_w, (0, 0))
                if self.world_has_none_of(c_s, c_se, c_e):
                    draw.point(self.box(slab_sz * 2 - 1), fill=black)
            else:
                draw.point(self.box(slab_sz - 1), fill=white)

        if self.world_has_all_of(c_s, c_e):
            if c_se in self.regions:
                region_img.paste(slab_w, self.box(slab_sz * 2))
                if self.world_has_none_of(c_n, c_nw, c_w):
                    draw.point((slab_sz, slab_sz), fill=black)
            else:
                draw.point(self.box(slab_sz * 2), fill=white)

        if self.world_has_all_of(c_s, c_w):
            if c_sw in self.regions:
                region_img.paste(slab_w, (0, slab_sz * 2))
                if self.world_has_none_of(c_n, c_ne, c_e):
                    draw.point((slab_sz * 2 - 1, slab_sz), fill=black)
            else:
                draw.point((slab_sz - 1, slab_sz * 2), fill=white)

        # endregion

        self.canvas.paste(region_img, self.canvas_coord(*coord, region_sz))


class MosaicMap(WorldMapBuilder):
    """
    Builds a Mosaic Map, Region-by-Region.
    """

    MosaicSlabSizeInPixels = 2

    def __init__(
        self,
        regions: Dict[MapCoord, DominantColors],
        corner1: MapCoord,
        corner2: MapCoord,
        slab_domc_keys: Sequence[str],
    ):
        """
        :param regions: A dict of MapCoord:DominantColors to build the map upon
        :param corner1: Coordinates for one corner of the map
        :param corner2: Coordinates for the corner of the map opposite to corner 1
        :param slab_domc_keys: A sequence of keys with which to color the Slabs.
        These are defined as class attributes in DominantColors
        """
        super().__init__(regions, None, corner1, corner2)

        self._domc_keys = slab_domc_keys
        # See https://docs.python.org/3/library/math.html#math.isqrt
        self._dim = 1 + isqrt(len(slab_domc_keys) - 1)

        canvas_box = MapCoord(self.width, self.height) * self.MosaicSlabSizeInPixels * self._dim
        self.canvas = Image.new("RGBA", canvas_box)

    def paste_slab(self, region: Image.Image, dimension: int, slab_colors: List[Tuple[int, int, int]]) -> None:
        """
        Pastes Slabs (squares of certain colors) into the Region image.

        :param region: The Region to which the Slabs will be pasted
        :param dimension: The dimension of the Region (in units of Slabs)
        :param slab_colors: The colors of the Slabs. The number of colors given must match the actual number of
        Slabs to be pasted to the Region.
        :return: None
        :raises AttributeError: if the number of colors is not equal to total number of Slabs
        """
        if len(slab_colors) != (dimension * dimension):
            raise AttributeError("Number of colors must match total number of Slabs!")
        sx, sy = 0, 0
        smax = dimension * self.MosaicSlabSizeInPixels
        slab_boxsz = (self.MosaicSlabSizeInPixels, self.MosaicSlabSizeInPixels)
        for color in slab_colors:
            loc = (sx, sy)
            slab_img = Image.new("RGB", slab_boxsz, color=color)
            region.paste(slab_img, loc)
            sx += self.MosaicSlabSizeInPixels
            if sx >= smax:
                sx = 0
                sy += self.MosaicSlabSizeInPixels

    def add_region(self, coord: MapCoord, domc: DominantColors) -> None:
        slab_sz = self.MosaicSlabSizeInPixels
        slab_boxsz = MapCoord(slab_sz, slab_sz)
        region_mosaic = Image.new("RGBA", slab_boxsz * self._dim)
        self.paste_slab(region_mosaic, self._dim, domc.to_list(*self._domc_keys))
        self.canvas.paste(region_mosaic, self.canvas_coord(*coord, slab_sz * self._dim))


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
    world_bounds = AreaBounds.from_coords(corner1, corner2)
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

        nightlights.add_region(coord, domc)
        mosaic_1x1.add_region(coord, domc)
        mosaic_2x2.add_region(coord, domc)
        mosaic_3x3.add_region(coord, domc)

    elapsed_t = time.monotonic() - start_t
    print(f"{count} Regions processed in {elapsed_t:,.2f} seconds")

    print("Saving canvases ... ", flush=True)
    start_t = time.monotonic()

    print(f"  => {nightlights.save(nightlights_path)}", flush=True)
    print(f"  => {mosaic_1x1.save(mosaic_path.with_suffix('.1x1.png'))}", flush=True)
    print(f"  => {mosaic_2x2.save(mosaic_path.with_suffix('.2x2.png'))}", flush=True)
    print(f"  => {mosaic_3x3.save(mosaic_path.with_suffix('.3x3.png'))}", flush=True)

    elapsed_t = time.monotonic() - start_t
    print(f"  {elapsed_t:,.2f} seconds")
