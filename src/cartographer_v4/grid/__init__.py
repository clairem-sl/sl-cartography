# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from pathlib import Path
from typing import Optional, TypedDict, Final

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont

from sl_maptools import CoordType, RegionsDBRecord3
from sl_maptools.knowns import KNOWN_AREAS, SUPPRESS_FOR_AREAS
from sl_maptools.utils import SLMapToolsConfig, ConfigReader


RGBATuple = tuple[int, int, int, int]


TEXT_RGBA: Final[RGBATuple] = (255, 255, 255, 191)
STROKE_WIDTH_NAME: Final[int] = 2
STROKE_WIDTH_COORD: Final[int] = 2
STROKE_RGBA: Final[RGBATuple] = (0, 0, 0, 191)
ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 32)


Config: SLMapToolsConfig = ConfigReader("config.toml")


_SQ: Optional[Image.Image] = None


class TextSettings(TypedDict):
    font: FreeTypeFont
    fill: RGBATuple
    stroke_width: int
    stroke_fill: RGBATuple


def make_grid(
    areamap: Path,
    regsdb: dict[CoordType, RegionsDBRecord3],
    out_dir: Path,
    validation_set: set[CoordType],
    regname_settings: TextSettings = None,
    coord_setttings: TextSettings = None,
    no_names: bool = False,
    no_coords: bool = False,
):
    global _SQ
    if _SQ is None:
        _SQ = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
        sq_draw = ImageDraw.Draw(_SQ)
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
    if coord_setttings is None:
        coord_setttings = {
            "font": ImageFont.truetype(Config.grids.font_coord, Config.grids.size_coord),
            "fill": TEXT_RGBA,
            "stroke_width": STROKE_WIDTH_NAME,
            "stroke_fill": STROKE_RGBA,
        }

    areaname = areamap.stem
    if areaname not in KNOWN_AREAS:
        print("  🈲 DOES NOT EXIST IN KNOWN_AREAS !!")
        return

    overlay_p = out_dir / (areaname + ".grid-overlay.png")
    gridc = None
    print("  => ", end="")
    if not overlay_p.exists():
        print("#️⃣ ", end="")
        bounds = KNOWN_AREAS[areaname]
        if areaname in SUPPRESS_FOR_AREAS:
            suppress = {xy for bounds in SUPPRESS_FOR_AREAS[areaname] for xy in bounds.xy_iterator()}
        else:
            suppress = set()
        x1, y1, x2, y2 = bounds
        size_x = (x2 - x1 + 1) * 256
        size_y = (y2 - y1 + 1) * 256
        gridc = Image.new("RGBA", (size_x, size_y), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(gridc)
        for i, xy in enumerate(bounds.xy_iterator(), start=1):
            if xy not in validation_set:
                continue
            if xy in suppress:
                continue
            x, y = xy
            cx = (x - x1) * 256
            cy = (y2 - y) * 256
            gridc.paste(_SQ, (cx, cy))
            regname = regsdb[xy]["current_name"]
            # print(regname)
            ty = cy + 4
            if not no_names:
                draw.text(
                    (cx + 5, ty),
                    f"{regname}",
                    **regname_settings
                )
                ty += 27
            if no_coords:
                draw.text(
                    (cx + 5, ty),
                    f"{x},{y}",
                    **coord_setttings
                )
            if (i % 10) == 0:
                print(".", end="", flush=True)
        gridc.save(overlay_p)
    print(f"{overlay_p}\n  => ", end="", flush=True)
    composite_p = out_dir / (areaname + ".composited.png")
    if not composite_p.exists():
        if gridc is None:
            with overlay_p.open("rb") as fin:
                gridc = Image.open(fin)
                gridc.load()
        print(f"💠 ", end="")
        with Image.open(areamap) as img:
            out = Image.alpha_composite(img, gridc)
            out.save(composite_p)
    print(f"{composite_p}", end="", flush=True)
