from typing import Iterable

import pytest
from PIL import Image, ImageDraw, ImageChops

from mosaic_v3.builder import NightlightsMap
from mosaic_v3.color_processing import DominantColors
from sl_maptools import MapCoord


def nl_corner_smooth() -> Image.Image:
    im = Image.new("L", (18, 18), color=0)
    whsq = Image.new("L", (12, 12), color=255)
    im.paste(whsq, (3, 3))
    draw = ImageDraw.Draw(im)
    for p in ((3, 3), (3, 14), (14, 3), (14, 14)):
        draw.point(p, fill=0)
    return im


def nl_elbows_smooth() -> Image.Image:
    im = Image.new("L", (27, 27), color=0)
    draw = ImageDraw.Draw(im)
    draw.rectangle(((3, 12), (23, 14)), fill=255)
    draw.rectangle(((12, 3), (14, 23)), fill=255)
    draw.rectangle(((11, 11), (15, 15)), fill=255)
    return im


def nl_pairs() -> Image.Image:
    im = Image.new("L", (36, 36), color=0)
    draw = ImageDraw.Draw(im)
    draw.rectangle(((3, 3), (14, 5)), fill=255)
    draw.rectangle(((30, 3), (32, 14)), fill=255)
    draw.rectangle(((21, 30), (32, 32)), fill=255)
    draw.rectangle(((3, 21), (5, 32)), fill=255)
    return im


def nl_scross() -> Image.Image:
    im = Image.new("L", (27, 27), color=0)
    whsq = Image.new("L", (3, 3), color=255)
    for p in ((12, 3), (3, 12), (21, 12), (12, 21)):
        im.paste(whsq, p)
    return im


def gen_dummy(*coords: tuple[int, int]):
    domc_dummy = DominantColors()
    regions = {
        MapCoord(*co): domc_dummy
        for co in coords
    }
    c2_x = max(coords, key=lambda i: i[0])[0]
    c2_y = max(coords, key=lambda i: i[1])[1]
    kwargs = {
        "regions": regions,
        "seen_rows": set(),
        "corner1": MapCoord(0, 0),
        "corner2": MapCoord(c2_x, c2_y)
    }
    return kwargs


# WARNING: Remember that these coordinates here are MAP COORDINATES in UNIT OF TILES
# (0, 0) is LOWER LEFT TILE, increasing to TOP RIGHT
test_smoothing_params = [
    pytest.param(
        ((0, 0), (1, 0), (0, 1), (1, 1)),
        nl_corner_smooth(),
        id="outer-corners"
    ),
    pytest.param(
        ((1, 0), (0, 1), (1, 1), (2, 1), (1, 2)),
        nl_elbows_smooth(),
        id="elbows"
    ),
    pytest.param(
        ((0, 3), (1, 3), (3, 3), (3, 2), (3, 0), (2, 0), (0, 0), (0, 1)),
        nl_pairs(),
        id="pairs"
    ),
    pytest.param(
        ((0, 1), (1, 0), (1, 2), (2, 1)),
        nl_scross(),
        id="socross"
    ),
]


@pytest.mark.parametrize("coords, expekt", test_smoothing_params)
def test_smoothing(coords: Iterable[tuple[int, int]], expekt: Image.Image):
    kwargs = gen_dummy(*coords)
    nl = NightlightsMap(**kwargs)
    for co, dum in nl.regions.items():
        nl.add_tile(co, dum)

    irgb = nl.canvas.convert("RGB")
    irgb.save("irgb.png")
    ergb = expekt.convert("RGB")
    ergb.save("ergb.png")
    assert irgb.size == ergb.size

    diff = ImageChops.difference(irgb, ergb)
    channels = diff.split()
    assert all(map(lambda c: c.getbbox() is None, channels))
