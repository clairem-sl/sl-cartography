# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from enum import Enum, auto, unique
from pathlib import Path
from typing import Optional, TypedDict, Final

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont

from sl_maptools import CoordType, RegionsDBRecord3
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import SLMapToolsConfig, ConfigReader


RGBATuple = tuple[int, int, int, int]


TEXT_RGBA: Final[RGBATuple] = (255, 255, 255, 191)
STROKE_WIDTH_NAME: Final[int] = 2
STROKE_WIDTH_COORD: Final[int] = 2
STROKE_RGBA: Final[RGBATuple] = (0, 0, 0, 191)
ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 32)


Config: SLMapToolsConfig = ConfigReader("config.toml")


class TextSettings(TypedDict):
    """Defines kwargs for PIL textdrawing"""

    font: FreeTypeFont
    fill: RGBATuple
    stroke_width: int
    stroke_fill: RGBATuple


@unique
class ExclusionMethod(Enum):
    """
    Supported exclusion methods for post-processing regions not part of an area
    """

    NONE = auto()
    """Do not hide regions excluded from areas (they will still not be labeled/gridded)"""
    HIDE = auto()
    """Hide regions excluded from areas"""
    TRANSP = auto()
    """Excluded areas are made semi-transparent, but not covered"""
    HATCHED = auto()
    """Excluded areas are covered by half-transparent hatched square"""
    FOG = auto()
    """Excluded areas are covered by a fog square (solid but half-transparent fill)"""


class GridMaker:
    """Creates the region grids for the high-res area maps"""

    def __init__(
        self,
        regions_db: dict[CoordType, RegionsDBRecord3],
        validation_set: set[CoordType],
        out_dir: Optional[Path] = None,
        regname_settings: Optional[TextSettings] = None,
        coord_setttings: Optional[TextSettings] = None,
    ):
        """
        :param regions_db: Database of existing regions
        :param validation_set: A set of coordinates for which we will draw a region tile
        :param out_dir: Directory to put the overlay & composited files
        :param regname_settings: Settings (font, size, etc.) for drawing the region names
        :param coord_setttings: Settings (font, size, etc.) for drawing the region coords
        """
        self.regions_db = regions_db
        self.validation_set = validation_set
        self.out_dir = out_dir

        self._sq = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
        sq_draw = ImageDraw.Draw(self._sq)
        ul = 0
        lr = 255
        for a in ALPHA_PATTERN:
            sq_draw.rectangle((ul, ul, lr, lr), width=1, outline=(255, 255, 255, a))
            ul += 1
            lr -= 1

        if regname_settings is None:
            regname_settings = {
                "font": ImageFont.truetype(Config.grids.font_name, Config.grids.size_name),
                "fill": TEXT_RGBA,
                "stroke_width": STROKE_WIDTH_NAME,
                "stroke_fill": STROKE_RGBA,
            }
        self.default_regname_settings = regname_settings

        if coord_setttings is None:
            coord_setttings = {
                "font": ImageFont.truetype(Config.grids.font_coord, Config.grids.size_coord),
                "fill": TEXT_RGBA,
                "stroke_width": STROKE_WIDTH_NAME,
                "stroke_fill": STROKE_RGBA,
            }
        self.default_coord_settings = coord_setttings

        self._cover_hr: Optional[Image.Image] = None
        self._cover_fog: Optional[Image.Image] = None

    @property
    def cover_hatched(self) -> Image.Image:
        """Image of hatched cover -- for regions not part of the area"""
        if self._cover_hr is None:
            _cov = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
            _drw = ImageDraw.Draw(_cov)
            ul = 0
            lr = 255
            for a in ALPHA_PATTERN:
                _drw.rectangle((ul, ul, lr, lr), width=1, outline=(255, 255, 255, a))
                ul += 1
                lr -= 1
            for c in range(31, 256, 32):
                _drw.line([(c - 4, 2), (2, c - 4)], fill=(255, 255, 255, 32), width=5)
                _drw.line([(c, 2), (2, c)], fill=(255, 255, 255, 32), width=5)
                _drw.line([(c, 0), (0, c)], fill=(255, 255, 255, 92), width=5)
                c = (255 + 32) - c  # noqa: PLW2901
                _drw.line([(c + 4, 253), (253, c + 4)], fill=(255, 255, 255, 32), width=5)
                _drw.line([(c, 253), (253, c)], fill=(255, 255, 255, 32), width=5)
                _drw.line([(c, 255), (255, c)], fill=(255, 255, 255, 92), width=5)
            self._cover_hr = _cov
        return self._cover_hr

    @property
    def cover_fog(self) -> Image.Image:
        """Image of fog cover -- for regions not part of the area"""
        if self._cover_fog is None:
            _cov = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
            _drw = ImageDraw.Draw(_cov)
            ul = 0
            lr = 255
            # for a in ALPHA_PATTERN:
            #     _drw.rectangle((ul, ul, lr, lr), width=1, outline=(255, 255, 255, a))
            #     ul += 1
            #     lr -= 1
            _drw.rectangle((ul, ul, lr, lr), width=0, fill=(255, 255, 255, 127))
            self._cover_fog = _cov
        return self._cover_fog

    def make_grid(
        self,
        areamap: Path,
        validate: bool = True,
        overwrite: bool = False,
        out_dir: Optional[Path] = None,
        no_names: bool = False,
        no_coords: bool = False,
        regname_settings: TextSettings = None,
        coord_setttings: TextSettings = None,
        exclusion_method: ExclusionMethod = ExclusionMethod.HIDE,
        save_names: bool = True,
    ) -> None:
        """
        Actually create the region grid on top of provided area map

        :param areamap: The area map file to be gridded
        :param validate: Whether to actually validate every coordinate against the validation_set
        :param overwrite: If True, overwrites existing file
        :param out_dir: Where to save the resulting files. Defaults to the out_dir parameter set during instantiation
        :param no_names: If True, does not draw the region names
        :param no_coords: If True, does not draw the coordinates
        :param regname_settings: Overrides the regname_settings parameter set during instantiation
        :param coord_setttings: Overrides the coord_settings parameter set during instantiation
        :param exclusion_method: The exclusion method to use for post-processing regions not part of the area
        :param save_names: If True, save a list of gridded regions into a text file
        """
        if out_dir is None:
            out_dir = self.out_dir or areamap.parent
        if regname_settings is None:
            regname_settings = self.default_regname_settings
        if coord_setttings is None:
            coord_setttings = self.default_coord_settings

        areaname = areamap.stem
        if areaname not in KNOWN_AREAS:
            print("  🈲 DOES NOT EXIST IN KNOWN_AREAS !!")
            return

        overlay_p = out_dir / (areaname + ".grid-overlay.png")
        gridc = None
        gridded_regions = []
        print("  => ", end="")
        if overwrite or not overlay_p.exists():
            print("#️⃣ ", end="")
            area = KNOWN_AREAS[areaname]
            x1, y1, x2, y2 = area.bounding_box
            size_x = (x2 - x1 + 1) * 256
            size_y = (y2 - y1 + 1) * 256
            gridc = Image.new("RGBA", (size_x, size_y), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(gridc)
            regs = 0

            if exclusion_method == ExclusionMethod.HIDE:
                xy_iterator = area.xy_iterator
            else:
                xy_iterator = area.bounding_box.xy_iterator

            for i, xy in enumerate(xy_iterator(), start=1):
                if validate and xy not in self.validation_set:
                    continue
                if xy not in self.regions_db:
                    continue
                regs += 1
                x, y = xy
                cx = (x - x1) * 256
                cy = (y2 - y) * 256
                if xy in area:
                    gridc.paste(self._sq, (cx, cy))
                    regname = self.regions_db[xy]["current_name"]
                    gridded_regions.append((regname, xy))
                    # print(regname)
                    ty = cy + 4
                    if not no_names:
                        draw.text((cx + 5, ty), f"{regname}", **regname_settings)
                        ty += 27
                    if not no_coords:
                        draw.text((cx + 5, ty), f"{x},{y}", **coord_setttings)
                elif exclusion_method == ExclusionMethod.FOG:
                    gridc.paste(self.cover_fog, (cx, cy))
                elif exclusion_method == ExclusionMethod.HATCHED:
                    gridc.paste(self.cover_hatched, (cx, cy))
                elif exclusion_method == ExclusionMethod.TRANSP:
                    pass
                if (i % 10) == 0:
                    print(".", end="", flush=True)
            print(f"[{regs}] ", end="", flush=True)
            gridc.save(overlay_p)
        print(f"{overlay_p}\n  => ", end="", flush=True)

        if save_names:
            gridded_regions.sort()
            regnames = out_dir / (areaname + ".regions.txt")
            with regnames.open("wt") as fout:
                for name, (x, y) in gridded_regions:
                    print(f"({x:4}, {y:4}) {name}", file=fout)

        composite_p = out_dir / (areaname + ".composited.png")
        if overwrite or not composite_p.exists():
            if gridc is None:
                with overlay_p.open("rb") as fin:
                    gridc = Image.open(fin)
                    gridc.load()
            print("💠 ", end="")
            with Image.open(areamap) as img:
                out = Image.alpha_composite(img, gridc)
                out.save(composite_p)
        print(f"{composite_p}", end="", flush=True)
