# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

from PIL import Image, ImageDraw

from mosaic_v3.color_processing import DominantColors
from sl_maptools import MapCoord


def build_mosaic(
    regions: Dict[MapCoord, DominantColors],
    seen_rows: Set[int],
    nightlights_path: Path,
    mosaic_path: Path,
    tot_width: int,
    tot_height: int,
):
    nl_tile_img_size = 9
    mo_subtile_sz = 2
    mo_subtile_boxsz = MapCoord(mo_subtile_sz, mo_subtile_sz)

    Image.MAX_IMAGE_PIXELS = (
        tot_width * nl_tile_img_size * tot_height * nl_tile_img_size
    )

    nl_black = 0
    nl_white = 255

    print("Building canvases")
    start_t = time.monotonic()
    # Gotta disable Type Checker for this line, because the type hint says "LA" is not supported, while in fact, it is
    # noinspection PyTypeChecker
    canvas_nightlights = Image.new(
        "LA", (tot_width * nl_tile_img_size, tot_height * nl_tile_img_size)
    )
    rect_row_black = Image.new(
        "L", (tot_width * nl_tile_img_size, nl_tile_img_size), color=nl_black
    )
    for y in seen_rows:
        canvas_nightlights.paste(
            rect_row_black, (0, nl_tile_img_size * (tot_height - y - 1))
        )
    sqw_3x3 = Image.new("L", (3, 3), color=nl_white)

    canvas_mosaic_1x1 = Image.new("RGBA", (tot_width * mo_subtile_sz, tot_height * mo_subtile_sz))
    canvas_mosaic_2x2 = Image.new("RGBA", (tot_width * mo_subtile_sz * 2, tot_height * mo_subtile_sz * 2))
    canvas_mosaic_3x3 = Image.new("RGBA", (tot_width * mo_subtile_sz * 3, tot_height * mo_subtile_sz * 3))

    # This is an 'unfold' of all(map(lambda x: x in regions_dict, items))
    # Easier to read, imho
    def world_has_all_of(*items):
        for i in items:
            assert isinstance(i, MapCoord)
            if not regions.get(i):
                return False
        return True

    def world_has_none_of(*items):
        for i in items:
            assert isinstance(i, MapCoord)
            if regions.get(i):
                return False
        return True

    def paste_subtiles(target: Image.Image, size: int, subtile_colors: List[Tuple[int, int, int]]):
        assert len(subtile_colors) == (size * size)
        sx, sy = 0, 0
        smax = size * mo_subtile_sz
        for color in subtile_colors:
            loc = (sx, sy)
            subtile = Image.new("RGBA", mo_subtile_boxsz, color=color)
            target.paste(subtile, loc)
            sx += mo_subtile_sz
            if sx >= smax:
                sx = 0
                sy += mo_subtile_sz

    # IMPORTANT NOTE:
    # Even on a full-sized map with 2000x2000 tiles, this process takes less than 10 seconds
    # So, please do NOT even consider of parallelizing this; it will be effort wasted for minimal
    # performance improvement.
    # Remember: premature optimization is the root of all evils
    # Focus the optimizations elsewhere.

    print(f"Processing world tiles... ", end="", flush=True)
    count = 0
    coord: MapCoord
    domc: DominantColors
    for count, (coord, domc) in enumerate(regions.items(), start=1):
        if count % 100 == 0:
            print("|", end="", flush=True)
            count = 0

        c_n = coord + (0, 1)
        c_e = coord + (1, 0)
        c_w = coord - (1, 0)
        c_s = coord - (0, 1)
        c_ne = coord + (1, 1)
        c_nw = coord + (-1, 1)
        c_se = coord + (1, -1)
        c_sw = coord + (-1, -1)

        tile_img = Image.new("L", (nl_tile_img_size, nl_tile_img_size), color=nl_black)
        tile_img.paste(sqw_3x3, (3, 3))
        draw = ImageDraw.Draw(tile_img)

        if c_n in regions:
            tile_img.paste(sqw_3x3, (3, 0))
        if c_e in regions:
            tile_img.paste(sqw_3x3, (6, 3))
        if c_w in regions:
            tile_img.paste(sqw_3x3, (0, 3))
        if c_s in regions:
            tile_img.paste(sqw_3x3, (3, 6))

        if world_has_all_of(c_n, c_e):
            if c_ne in regions:
                tile_img.paste(sqw_3x3, (6, 0))
                if world_has_none_of(c_se, c_s, c_sw, c_w, c_nw):
                    draw.point((3, 5), fill=nl_black)
            else:
                draw.point((6, 2), fill=nl_white)
        if world_has_all_of(c_n, c_w):
            if c_nw in regions:
                tile_img.paste(sqw_3x3, (0, 0))
                if world_has_none_of(c_sw, c_s, c_se, c_e, c_ne):
                    draw.point((5, 5), fill=nl_black)
            else:
                draw.point((2, 2), fill=nl_white)
        if world_has_all_of(c_s, c_e):
            if c_se in regions:
                tile_img.paste(sqw_3x3, (6, 6))
                if world_has_none_of(c_ne, c_n, c_nw, c_w, c_sw):
                    draw.point((3, 3), fill=nl_black)
            else:
                draw.point((6, 6), fill=nl_white)
        if world_has_all_of(c_s, c_w):
            if c_sw in regions:
                tile_img.paste(sqw_3x3, (0, 6))
                if world_has_none_of(c_nw, c_n, c_ne, c_e, c_se):
                    draw.point((5, 3), fill=nl_black)
            else:
                draw.point((2, 6), fill=nl_white)

        canvas_coord = MapCoord(coord.x, tot_height - coord.y - 1)

        canvas_nightlights.paste(tile_img, tuple(canvas_coord * nl_tile_img_size))

        tile_mosaic_1x1 = Image.new("RGBA", mo_subtile_boxsz, color=domc["full"])
        canvas_mosaic_1x1.paste(tile_mosaic_1x1, tuple(canvas_coord * mo_subtile_sz))

        tile_mosaic_2x2 = Image.new("RGBA", mo_subtile_boxsz * 2)
        paste_subtiles(tile_mosaic_2x2, 2, domc.to_list("q_nw", "q_ne", "q_sw", "q_se"))
        canvas_mosaic_2x2.paste(tile_mosaic_2x2, tuple(canvas_coord * (mo_subtile_sz * 2)))

        tile_mosaic_3x3 = Image.new("RGBA", mo_subtile_boxsz * 3)
        paste_subtiles(
            tile_mosaic_3x3, 3, domc.to_list("n_nw", "n_no", "n_ne", "n_we", "n_ce", "n_ea", "n_sw", "n_so", "n_se")
        )
        canvas_mosaic_3x3.paste(tile_mosaic_3x3, tuple(canvas_coord * (mo_subtile_sz * 3)))

    elapsed_t = time.monotonic() - start_t
    print(f"{count} tiles processed in {elapsed_t:,.2f} seconds")

    print("Saving canvases ... ", end="", flush=True)
    start_t = time.monotonic()

    nightlights_path.parent.mkdir(parents=True, exist_ok=True)
    canvas_nightlights.save(nightlights_path, optimize=True)

    mosaic_path.parent.mkdir(parents=True, exist_ok=True)
    canvas_mosaic_1x1.save(mosaic_path.with_suffix(".1x1.png"), optimize=True)
    canvas_mosaic_2x2.save(mosaic_path.with_suffix(".2x2.png"), optimize=True)
    canvas_mosaic_3x3.save(mosaic_path.with_suffix(".3x3.png"), optimize=True)

    elapsed_t = time.monotonic() - start_t
    print(f"{elapsed_t:,.2f} seconds")
