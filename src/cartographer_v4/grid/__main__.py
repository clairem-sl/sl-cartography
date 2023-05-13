import pickle
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from sl_maptools import CoordType, RegionsDBRecord
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.validator import get_bonnie_coords


FONT_SIZE: Final[int] = 16
STROKE_WIDTH: Final[int] = 2

ALPHA_PATTERN: Final[tuple[int, ...]] = (96, 32)


def main():
    # Disable DecompressionBombWarning
    Image.MAX_IMAGE_PIXELS = None

    areamaps_dir = Path(r"C:\Cache\SL-Carto\AreaMaps")
    areagrid_dir = areamaps_dir / "Grids"
    areagrid_dir.mkdir(exist_ok=True)

    sq = Image.new("RGBA", (256, 256), color=(255, 255, 255, 0))
    sq_draw = ImageDraw.Draw(sq)

    ul = 0
    lr = 255
    for a in ALPHA_PATTERN:
        sq_draw.rectangle((ul, ul, lr, lr), width=1, outline=(255, 255, 255, a))
        ul += 1
        lr -= 1

    font = ImageFont.truetype(r"C:\Windows\Fonts\comic.ttf", FONT_SIZE)
    w, h = font.getsize("M", stroke_width=STROKE_WIDTH)
    h_offs = 256 - 3 - h

    validation_set: set[CoordType] = set()
    with Path(r"C:\Cache\SL-Carto\RegionsDB2.pkl").open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord] = pickle.load(fin)
    validation_set.update(k for k, v in regsdb.items() if v["current_name"])
    bonnie_coords = get_bonnie_coords(None, True)
    print()
    validation_set.intersection_update(bonnie_coords)

    for areamap in areamaps_dir.glob("*.png"):
        print(f"{areamap} => ", end="", flush=True)
        areaname = areamap.stem
        bounds = KNOWN_AREAS[areaname]
        x1, y1, x2, y2 = bounds
        size_x = (x2 - x1 + 1) * 256
        size_y = (y2 - y1 + 1) * 256
        gridc = Image.new("RGBA", (size_x, size_y), color=(255, 255, 255, 0))
        draw = ImageDraw.Draw(gridc)
        for xy in bounds.xy_iterator():
            if xy not in validation_set:
                continue
            x, y = xy
            cx = (x - x1) * 256
            cy = (y2 - y) * 256
            gridc.paste(sq, (cx, cy))
            regname = regsdb[xy]["current_name"]
            # print(regname)
            draw.text((cx + 5, cy + 4), regname, font=font, fill=(255, 255, 255, 255), stroke_width=STROKE_WIDTH, stroke_fill=(0, 0, 0, 255))

        targ = areagrid_dir / (areaname + ".gridonly.png")
        gridc.save(targ)

        targ = areagrid_dir / (areaname + ".grid.png")
        with Image.open(areamap) as img:
            out = Image.alpha_composite(img, gridc)
            out.save(targ)
        print(f"{targ}", flush=True)


if __name__ == "__main__":
    main()
