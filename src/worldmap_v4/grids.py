# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import Final, Literal, Optional, Protocol, cast

from PIL import Image, ImageDraw, ImageFont

from sl_maptools import COORD_RANGE

FONT_NAME = r"C:\Games\KokuaViewer\fonts\Roboto-Bold.ttf"
GRID_THICKNESS = 5

GRIDSECTOR_SIZE: Final[int] = 100

# fmt: off
GRID_COLS: Final[list[str]] = [
    "AA", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U"
]
# fmt: on

ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 64, 32)

OVERLAY_VARIANTS = {
    "white": {
        "back_color": (0, 0, 0),
        "rect_color": (255, 255, 255),
    },
    "black": {
        "back_color": (255, 255, 255),
        "rect_color": (0, 0, 0),
    },
}


class Options(Protocol):
    worldmapfile: Optional[Path]
    source_type: Literal["mos", "nl"]
    source_dir: Optional[Path]


_TYPE_CHOICES = {
    frozenset(["nl", "nightlights"]): "nl",
    frozenset(["mos", "mosaic"]): "mos",
}


def get_options() -> Options:
    parser = argparse.ArgumentParser("worldmap_v4.grids")

    _type_choices = set(chain.from_iterable(_TYPE_CHOICES))
    parser.add_argument("--source-type", type=str, choices=_type_choices, required=True)
    parser.add_argument("--source-dir", type=Path, default=None)

    parser.add_argument("worldmapfile", type=Path, default=None, nargs="?")

    _opts = cast(Options, parser.parse_args())
    for k, v in _TYPE_CHOICES:
        if _opts.source_type in k:
            _opts.source_type = v
            break

    return _opts


def main(opts: Options):
    # worldmap_dir = Path(r"C:\Cache\SL-Carto\WorldMaps")
    # worldmap_p = worldmap_dir / "worldmap4_mosaic_5x5.png"
    worldmap_p = opts.worldmapfile
    if worldmap_p is None:
        src_dir = opts.source_dir
        if not src_dir.exists() or not src_dir.is_dir():
            raise RuntimeError(f"Not a directory: {src_dir}")
        if opts.source_type == "nl":
            patt = "worldmap4_nightlights_*"
        else:
            patt = "worldmap4_mosaic_*"
        files = [f for f in src_dir.glob(patt)]
        if not files:
            raise FileNotFoundError(f"Cannot find '{patt}' in {src_dir}")
        files.sort(key=lambda f: f.stat().st_mtime)
        worldmap_p = files[-1].expanduser().absolute()
    worldmap_m = datetime.fromtimestamp(worldmap_p.stat().st_mtime)

    Image.MAX_IMAGE_PIXELS = None

    min_co, max_co = COORD_RANGE

    print(f"Loading worldmap {worldmap_p} (m = {worldmap_m})")
    with worldmap_p.open("rb") as fin:
        worldmap = Image.open(fin)
        worldmap.load()
    sx, sy = worldmap.size
    reg_sz, rem = divmod(sx, max_co + 1)
    if sx != sy or rem != 0:
        raise RuntimeError(f"File size funky: {sx}, {sy}")
    sect_sz = reg_sz * GRIDSECTOR_SIZE
    padded_sz = ((sx + sect_sz - 1) // sect_sz) * sect_sz
    canvas_sz = padded_sz + 2 * sect_sz

    gridsector_dir = worldmap_p.parent / "GridSectors"
    gridsector_dir.mkdir(exist_ok=True)
    common_kwargs = {
        "font": ImageFont.truetype(str(FONT_NAME), 480),
        "fill": (255, 255, 255, 255),
        "anchor": "mm",
        "stroke_width": 50,
        "stroke_fill": (0, 0, 0, 255),
    }

    for variant, parms in OVERLAY_VARIANTS.items():
        print(f"Making Grids - {variant}")
        back_color = parms["back_color"] + (0,)

        print("  Padding worldmap")
        padded_map = Image.new("RGBA", (padded_sz, padded_sz), color=back_color)
        padded_map.paste(worldmap, (0, (padded_sz - sx)))

        print("  Making grids", end="", flush=True)
        sq = Image.new("RGBA", (sect_sz, sect_sz), color=back_color)
        draw = ImageDraw.Draw(sq)
        ul = 0
        lr = sect_sz - 1
        for a in ALPHA_PATTERN:
            colr = parms["rect_color"] + (a,)
            for _ in range(GRID_THICKNESS):
                draw.rectangle((ul, ul, lr, lr), width=1, outline=colr)
                ul += 1
                lr -= 1
        gridsec_overlay = Image.new("RGBA", (padded_sz, padded_sz), color=back_color)
        i = 0
        for cx in range(0, padded_sz, sect_sz):
            for cy in range(0, padded_sz, sect_sz):
                i += 1
                if (i % 10) == 0:
                    print(".", end="", flush=True)
                gridsec_overlay.paste(sq, (cx, cy))
        print()

        print(f"  Making canvas")
        canvas = Image.new("RGBA", (canvas_sz, canvas_sz), color=back_color)
        canvas.paste(Image.alpha_composite(padded_map, gridsec_overlay), (sect_sz, sect_sz))
        # noinspection PyUnusedLocal
        padded_map = None
        # noinspection PyUnusedLocal
        gridsec_overlay = None

        draw = ImageDraw.Draw(canvas)
        print("  Drawing labels")
        cy = sect_sz // 2
        for x, label in enumerate(GRID_COLS):
            cx = sect_sz // 2 + (x + 1) * sect_sz
            draw.text((cx, cy), label, **common_kwargs)
            draw.text((cx, canvas_sz - cy), label, **common_kwargs)
        cx = sect_sz // 2
        for y in range(0, 22):
            cy = canvas_sz - (sect_sz // 2 + (y + 1) * sect_sz)
            draw.text((cx, cy), str(y), **common_kwargs)
            draw.text((canvas_sz - cx, cy), str(y), **common_kwargs)

        print("  Saving ...", end="", flush=True)
        targ_p = gridsector_dir / f"WorldGridSectors_{opts.source_type}_{variant}.png"
        targ_p.unlink(missing_ok=True)
        canvas.save(targ_p)
        print(f" {targ_p}", flush=True)


if __name__ == "__main__":
    main(get_options())
