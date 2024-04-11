# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from enum import Enum, auto, unique
from typing import TYPE_CHECKING, Final, TypedDict

from PIL import Image, ImageDraw, ImageFont

from sl_maptools.config import DefaultConfig as Config, FontSpec
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import make_pnginfo

if TYPE_CHECKING:
    from pathlib import Path

    from PIL.ImageFont import FreeTypeFont

    from sl_maptools import AreaDescriptor, CoordType, RegionsDBRecord3


RGBATuple = tuple[int, int, int, int]


TEXT_RGBA: Final[RGBATuple] = (255, 255, 255, 191)
STROKE_WIDTH_NAME: Final[int] = 2
STROKE_WIDTH_COORD: Final[int] = 2
# STROKE_RGBA: Final[RGBATuple] = (0, 0, 0, 191)
STROKE_RGBA: Final[RGBATuple] = (0, 0, 0, 159)
ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 32)

COORD_SHIFT_RATIO: float = 1.05


class TextSettings(TypedDict):
    """Defines kwargs for PIL textdrawing"""

    font: FreeTypeFont
    fill: RGBATuple
    stroke_width: int
    stroke_fill: RGBATuple
    overdraw: bool


@unique
class ExclusionMethod(Enum):
    """
    Supported exclusion methods for post-processing regions not part of an area
    """

    NONE = auto()
    """Do not hide regions excluded from areas (they will still not be labeled/latticed)"""
    HIDE = auto()
    """Hide regions excluded from areas"""
    TRANSP = auto()
    """Excluded areas are made semi-transparent, but not covered"""
    HATCHED = auto()
    """Excluded areas are covered by half-transparent hatched square"""
    FOG = auto()
    """Excluded areas are covered by a fog square (solid but half-transparent fill)"""


def _getfont(settings: FontSpec) -> FreeTypeFont:
    _font = ImageFont.truetype(settings.font, settings.size)
    if settings.variant is not None:
        _font.set_variation_by_name(settings.variant)
    return _font


class LatticeMaker:
    """Creates the region lattice for the high-res area maps"""

    def __init__(
        self,
        regions_db: dict[CoordType, RegionsDBRecord3],
        validation_set: set[CoordType],
        out_dir: Path | None = None,
        exclusion_method: ExclusionMethod = ExclusionMethod.HIDE,
        regname_settings: TextSettings | None = None,
        coord_setttings: TextSettings | None = None,
    ):
        """
        :param regions_db: Database of existing regions
        :param validation_set: A set of coordinates for which we will draw a region tile
        :param out_dir: Directory to put the overlay & composited files
        :param exclusion_method: The exclusion method to use for post-processing regions not part of the area
        :param regname_settings: TextSettings for Region Name label
        :param coord_setttings: TextSettings for Coordinates label
        """
        self.regions_db = regions_db
        self.validation_set = validation_set
        self.out_dir = out_dir
        self.exclusion_method = exclusion_method

        self._sq = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
        sq_draw = ImageDraw.Draw(self._sq)
        ul = 0
        lr = 255
        for a in ALPHA_PATTERN:
            sq_draw.rectangle((ul, ul, lr, lr), width=1, outline=(255, 255, 255, a))
            ul += 1  # noqa: SIM113
            lr -= 1

        if regname_settings:
            self.regname_settings = regname_settings
        else:
            self.regname_settings: TextSettings = {
                "font": _getfont(Config.lattice.name),
                "fill": TEXT_RGBA,
                "stroke_width": STROKE_WIDTH_NAME,
                "stroke_fill": STROKE_RGBA,
                "overdraw": Config.lattice.name.overdraw,
            }

        if coord_setttings:
            self.coord_settings = coord_setttings
        else:
            self.coord_settings: TextSettings = {
                "font": _getfont(Config.lattice.coord),
                "fill": TEXT_RGBA,
                "stroke_width": STROKE_WIDTH_COORD,
                "stroke_fill": STROKE_RGBA,
                "overdraw": Config.lattice.coord.overdraw,
            }

        self._cover_hr: Image.Image | None = None
        self._cover_fog: Image.Image | None = None

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
                ul += 1  # noqa: SIM113
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

    def _make_overlay(
        self,
        area: AreaDescriptor,
        validate: bool,
        no_names: bool,
        no_coords: bool,
    ) -> tuple[Image, list[tuple[str, tuple[int, int]]]]:
        print("#️⃣ ", end="")
        x1, y1, x2, y2 = area.bounding_box
        size_x = (x2 - x1 + 1) * 256
        size_y = (y2 - y1 + 1) * 256
        overlay = Image.new("RGBA", (size_x, size_y), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        regs = 0

        if self.exclusion_method == ExclusionMethod.HIDE:
            xy_iterator = area.xy_iterator
        else:
            xy_iterator = area.bounding_box.xy_iterator

        def draw_text(_x: int, _y: int, text: str, text_settings: TextSettings) -> None:
            _settings: dict = text_settings.copy()
            overdraw = _settings["overdraw"]
            del _settings["overdraw"]
            _co = _x, _y
            draw.text(_co, text, **text_settings)
            if overdraw:
                del _settings["stroke_width"]
                del _settings["stroke_fill"]
                draw.text(_co, text, **_settings)

        overlay_regions = []
        coord_shift: int = round((self.regname_settings["font"].getbbox("My")[-1] + 1) * COORD_SHIFT_RATIO)
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
                overlay.paste(self._sq, (cx, cy))
                regname = self.regions_db[xy]["current_name"]
                overlay_regions.append((regname, xy))
                # print(regname)
                ty = cy + 4
                if not no_names:
                    draw_text(cx + 5, ty, regname, self.regname_settings)
                    ty += coord_shift
                if not no_coords:
                    draw_text(cx + 5, ty, f"{x},{y}", self.coord_settings)
            elif self.exclusion_method == ExclusionMethod.FOG:
                overlay.paste(self.cover_fog, (cx, cy))
            elif self.exclusion_method == ExclusionMethod.HATCHED:
                overlay.paste(self.cover_hatched, (cx, cy))
            elif self.exclusion_method == ExclusionMethod.TRANSP:
                pass
            if (i % 50) == 0:
                print(".", end="", flush=True)
        print(f"[{regs}] ", end="", flush=True)
        return overlay, overlay_regions

    def make_lattice(
        self,
        areamap: Path,
        validate: bool = True,
        overwrite: bool = False,
        out_dir: Path | None = None,
        no_names: bool = False,
        no_coords: bool = False,
        save_names: bool = True,
        *,
        add_info: bool = True,
    ) -> None:
        """
        Actually create the region lattice on top of provided area map

        :param areamap: The area map file to create a lattice upon
        :param validate: Whether to actually validate every coordinate against the validation_set
        :param overwrite: If True, overwrites existing file
        :param out_dir: Where to save the resulting files. Defaults to the out_dir parameter set during instantiation
        :param no_names: If True, does not draw the region names
        :param no_coords: If True, does not draw the coordinates
        :param save_names: If True, save a list of regions in the lattice into a text file
        :param add_info: If True, add metadata
        """
        if out_dir is None:
            out_dir = self.out_dir or areamap.parent

        areaname = areamap.stem
        if areaname not in KNOWN_AREAS:
            print("  🈲 DOES NOT EXIST IN KNOWN_AREAS !!")
            return

        overlay_p = out_dir / (areaname + ".lattice-overlay.png")
        lattice = None
        lattice_regions = []
        print("  => ", end="")
        if overwrite or not overlay_p.exists():
            lattice, lattice_regions = self._make_overlay(
                KNOWN_AREAS[areaname],
                validate=validate,
                no_names=no_names,
                no_coords=no_coords,
            )
            info = make_pnginfo(f"{areaname}-Lattice", f"Lattice of {areaname}", Config) if add_info else None
            lattice.save(overlay_p, optimize=True, pnginfo=info)
        print(f"{overlay_p}\n  => ", end="", flush=True)

        if save_names and lattice_regions:
            lattice_regions.sort()
            regnames = out_dir / (areaname + ".regions.txt")
            with regnames.open("wt") as fout:
                for name, (x, y) in lattice_regions:
                    print(f"({x:4}, {y:4}) {name}", file=fout)

        composite_p = out_dir / (areaname + ".composited.png")
        if overwrite or not composite_p.exists():
            if lattice is None:
                with overlay_p.open("rb") as fin:
                    lattice = Image.open(fin)
                    lattice.load()
            print("💠 ", end="")
            with Image.open(areamap) as img:
                out = Image.alpha_composite(img, lattice)
                info = (
                    make_pnginfo(
                        f"{areaname}-Composited",
                        (
                            f"High-res Composited Map of {areaname}, composited from the area's lattice on top of "
                            f"the unadorned high-res map of the area itself"
                        ),
                        Config,
                    )
                    if add_info
                    else None
                )
                out.save(composite_p, optimize=True, pnginfo=info)
        print(f"{composite_p}", end="", flush=True)
