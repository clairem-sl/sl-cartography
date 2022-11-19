from pathlib import Path
from typing import Iterable

import pytest
from _pytest.mark import ParameterSet
from PIL import Image

from sl_maptools import MapCoord, MapTile
from src.mosaic_v3.color_processing import DominantColors, getbox, getdom

ThreeInts = tuple[int, int, int]
FourInts = tuple[int, int, int, int]


modes = ["RGB", "RGBA"]

one_colors: Iterable[ThreeInts] = [
    (0, 0, 0),
    (127, 127, 127),
    (255, 255, 255),
]


@pytest.mark.parametrize("mode", modes)
@pytest.mark.parametrize("color", one_colors)
def test_getdom_onecolor(mode: str, color: ThreeInts):
    # noinspection PyTypeChecker
    im = Image.new(mode, (256, 256), color=color)
    for k in range(1, 11):
        assert getdom(im, kmeans=k) == color


box_vals: Iterable[ParameterSet] = [
    pytest.param((1, 1, 0, 0), (0, 0, 256, 256), id="full"),
    pytest.param((2, 1, 0, 0), (0, 0, 128, 128), id="q_nw"),
    pytest.param((2, 1, 1, 0), (128, 0, 256, 128), id="q_ne"),
    pytest.param((2, 1, 0, 1), (0, 128, 128, 256), id="q_sw"),
    pytest.param((16, 6, 0, 0), (0, 0, 96, 96), id="n_nw"),
    pytest.param((16, 6, 5, 0), (80, 0, 176, 96), id="n_no"),
    pytest.param((16, 6, 0, 5), (0, 80, 96, 176), id="n_we"),
]


@pytest.mark.parametrize("boxparms, expekt", box_vals)
def test_getbox(boxparms: FourInts, expekt: FourInts):
    assert getbox(*boxparms) == expekt


test_tiles = (
    Path("tests") / Path("mosaic_v3") / "map-1-1000-1000-objects.jpg",
    Path("tests") / Path("mosaic_v3") / "map-1-1004-1000-objects.jpg",
)


test_files_expect = [
    (test_tiles[0], 1, (70, 89, 48)),
    (test_tiles[0], 3, (70, 89, 48)),
    (test_tiles[0], 5, (70, 89, 48)),
    (test_tiles[1], 1, (58, 90, 109)),
    (test_tiles[1], 3, (58, 90, 109)),
    (test_tiles[1], 5, (58, 90, 109)),
]


@pytest.mark.parametrize("fname, kmeans, expekt", test_files_expect)
def test_getdom_file(fname: Path, kmeans: int, expekt: ThreeInts):
    with Image.open(fname) as im:
        assert getdom(im, kmeans=kmeans) == expekt


test_files_expect_domc = [
    (
        test_tiles[0],
        {
            "full": (70, 89, 48),
            "n_ce": (73, 90, 54),
            "n_ea": (17, 17, 16),
            "n_ne": (71, 88, 51),
            "n_no": (77, 93, 56),
            "n_nw": (75, 93, 56),
            "n_se": (72, 91, 53),
            "n_so": (75, 91, 54),
            "n_sw": (70, 85, 51),
            "n_we": (78, 95, 58),
            "q_ne": (75, 91, 55),
            "q_nw": (70, 88, 51),
            "q_se": (72, 90, 53),
            "q_sw": (75, 90, 55),
        },
    ),
    (
        test_tiles[1],
        {
            "full": (58, 90, 109),
            "n_ce": (55, 89, 108),
            "n_ea": (65, 97, 116),
            "n_ne": (56, 89, 108),
            "n_no": (59, 92, 111),
            "n_nw": (67, 99, 117),
            "n_se": (60, 93, 112),
            "n_so": (60, 93, 112),
            "n_sw": (62, 94, 113),
            "n_we": (62, 95, 114),
            "q_ne": (59, 92, 110),
            "q_nw": (63, 95, 113),
            "q_se": (56, 89, 108),
            "q_sw": (53, 87, 105),
        },
    ),
]


@pytest.mark.parametrize("fpath, expekt", test_files_expect_domc)
def test_dominant_colors(fpath: Path, expekt: dict[str, ThreeInts]):
    with Image.open(fpath) as im:
        im.load()
        tile = MapTile(MapCoord(0, 0), im)
        domc = DominantColors.from_tile(tile)
        assert domc._domc == expekt
