# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import functools
from typing import Dict, Iterable, List, Self, Tuple, cast

from colorthief import ColorThief
from PIL import Image

from sl_maptools import MapCoord, MapTile

EMERGENCY_TRANSFORM: Dict[MapCoord, Tuple[int, int, int]] = {
    # Region no longer exists as of 2022-11-09
    # # Pure white tile called "Spartan Realms"
    # MapCoord(1012, 1341): (255, 255, 255),
    # "Nos Nocte", pure white if zoomed all the way in, but like a beach if zoomed out slightly
    MapCoord(576, 1250): (255, 255, 255),
    # "VWR Test", pure white
    MapCoord(920, 950): (255, 255, 255),
    # "Noweeta", pure white -- checked 2022-11-09
    MapCoord(934, 1130): (255, 255, 255),
}


class ColorThief2(ColorThief):
    # This is a workaround because original ColorThief implementation insists on reading from a file,
    # while in our usage we never have a file to begin with.
    def __init__(self, source):
        if isinstance(source, Image.Image):
            self.image = source
        else:
            super().__init__(source)


def getdom(im: Image.Image, kmeans: int) -> Tuple[int, int, int]:
    quant = im.quantize(colors=16, kmeans=kmeans)
    rgb = quant.convert("RGB")
    colors = cast(List[Tuple[int, Tuple[int, int, int]]], rgb.getcolors())
    freq, dom = max(colors, key=lambda x: x[0])
    return dom


def getbox(splits: int, subreg_sz: int, x_offset: int, y_offset: int) -> Tuple[int, int, int, int]:
    """
    Returns proper box tuple for image cropping

    :param splits: Split tile to how many squares per dimension (we'll get splits x splits number of squares)
    :param subreg_sz: How many squares per subtile (subreg_sz x subreg_sz squares per subtile)
    :param x_offset: Subtile offset from left
    :param y_offset: Subtile offset from top
    :return: Box tuple suitable for pillow's Image.crop()
    """
    subtile_size = 256 // splits
    return (
        x_offset * subtile_size,
        y_offset * subtile_size,
        (x_offset + subreg_sz) * subtile_size,
        (y_offset + subreg_sz) * subtile_size,
    )


# Quarters: Split region into 2x2 subtiles and 2x2 subregions (each subregion = 1x1 subtile)
getbox_q = functools.partial(getbox, 2, 1)


# Ninths: Split region into 3x3 _overlapping_ subregions
#         We first split the tile into 16x16 subtiles
#         Then each subregion is 6x6 subtiles
#         This gives 1-subtile overlap between adjacent subregions
getbox_n = functools.partial(getbox, 16, 6)


# For 5x5, use one of these strategies:
# n=5 c=52 b=1  gcd=1  ==> splits=256 sz=52 offset=51
# n=5 c=56 b=6  gcd=2  ==> splits=128 sz=28 offset=25
# n=5 c=60 b=11 gcd=1  ==> splits=256 sz=60 offset=49
# n=5 c=64 b=16 gcd=16 ==> splits=16  sz=4  offset=3
#
# Then:
#   1) create the partial func getbox_25 (or getbox_5) with the above params
#   2) create the relevant key:value pairs in DominantColors.CropBox
#   3) regenerate the whole state file
#
# For the key names, suggested like this:
#
#   nw2  nwn  n2  nen  ne2
#   nww  nw1  n1  ne1  nee
#    w2   w1  c0  e1   e2
#   sww  sw1  s1  se1  see
#   sw2  sws  s2  ses  se2


class DominantColors:
    """
    Calculates the dominant colors of a tile and its subtiles.

    Currently hardcoded into calculating the dominant colors of the following:
    - The whole tile ("full")
    - Non-overlapping 2x2 subtiles ("quarters" or "q"s)
    - Slightly overlapping 3x3 subtiles ("ninths" or "n"s)

    For the 3x3 subtiles, the strategy is to first split the tile into 16x16 squares,
    then create 9 subtiles each of 6x6 squares. This will cause a 1-square overlap between
    adjacent subtiles.

    All calculated dominant colors are stored in a dict with a label that describes its
    position in the tile.
    """

    CropBox: Dict[str, Tuple[int, int, int, int]] = {
        "full": (0, 0, 256, 256),
        "q_nw": (getbox_q(0, 0)),
        "q_ne": (getbox_q(0, 1)),
        "q_sw": (getbox_q(1, 0)),
        "q_se": (getbox_q(1, 1)),
        "n_nw": (getbox_n(0, 0)),
        "n_no": (getbox_n(5, 0)),
        "n_ne": (getbox_n(10, 0)),
        "n_ea": (getbox_n(0, 5)),
        "n_ce": (getbox_n(5, 5)),
        "n_we": (getbox_n(10, 5)),
        "n_sw": (getbox_n(0, 10)),
        "n_so": (getbox_n(5, 10)),
        "n_se": (getbox_n(10, 10)),
    }
    QualBySize = {
        256: 3,  # full tile
        128: 2,  # quarter tile, size is 256 // 2
        96: 1,  # ninth tile, size is (256 // 16) * 6
    }

    Keys_1x1 = ("full",)
    Keys_2x2 = ("q_nw", "q_ne", "q_sw", "q_se")
    Keys_3x3 = ("n_nw", "n_no", "n_ne", "n_we", "n_ce", "n_ea", "n_sw", "n_so", "n_se")

    def __init__(self):
        self._domc: Dict[str, Tuple[int, int, int]] = {}

    def __getitem__(self, item) -> Tuple[int, int, int]:
        return self._domc[item]

    def __setitem__(self, key, value):
        self._domc[key] = value

    def __contains__(self, item):
        return item in self._domc

    def __repr__(self):
        return repr(self._domc)

    def __str__(self):
        return str(self._domc)

    @classmethod
    def calc_domc(cls, img: Image.Image, key: str) -> Tuple[int, int, int]:
        cropbox = cls.CropBox[key]
        im = img.crop(cropbox)
        sz, _ = im.size
        qual = cls.QualBySize[sz]
        # return ColorThief2(im).get_color(qual)
        return getdom(im, qual)

    @classmethod
    def from_tile(cls, tile: MapTile) -> DominantColors:
        imcopy = tile.image.copy()
        domc = cls()
        for key in cls.CropBox.keys():
            # noinspection PyBroadException
            try:
                col = cls.calc_domc(imcopy, key)
            except Exception:
                if tile.coord not in EMERGENCY_TRANSFORM:
                    print(f"get_color failure for {tile.coord} {key}")
                    raise
                col = EMERGENCY_TRANSFORM[tile.coord]
            domc[key] = col
        return domc

    @classmethod
    def from_serialized(cls, raw_dict: Dict[str, Iterable[int]]) -> Self:
        domc = cls()
        for k, v in raw_dict.items():
            domc[k] = tuple(v)
        return domc

    def encode(self) -> Dict[str, Tuple[int, int, int]]:
        return self._domc

    def to_list(self, *indexes) -> List[Tuple[int, int, int]]:
        return [self._domc[idx] for idx in indexes]
