# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import functools
from typing import Dict, Iterable, List, Self, Tuple, cast

from PIL import Image

from sl_maptools import MapCoord, MapRegion

EMERGENCY_TRANSFORM: Dict[MapCoord, Tuple[int, int, int]] = {
    # Region no longer exists as of 2022-11-09
    # # Pure white Region called "Spartan Realms"
    # MapCoord(1012, 1341): (255, 255, 255),
    # "Nos Nocte", pure white if zoomed all the way in, but like a beach if zoomed out slightly
    MapCoord(576, 1250): (255, 255, 255),
    # "VWR Test", pure white
    MapCoord(920, 950): (255, 255, 255),
    # "Noweeta", pure white -- checked 2022-11-09
    MapCoord(934, 1130): (255, 255, 255),
}


def getdom(im: Image.Image, kmeans: int) -> Tuple[int, int, int]:
    quant = im.quantize(colors=16, kmeans=kmeans)
    rgb = quant.convert("RGB")
    colors = cast(List[Tuple[int, Tuple[int, int, int]]], rgb.getcolors())
    freq, dom = max(colors, key=lambda x: x[0])
    return dom


def getbox(splits: int, subreg_sz: int, x_offset: int, y_offset: int) -> Tuple[int, int, int, int]:
    """
    Returns proper box tuple for image cropping

    :param splits: Split region to how many fascias per dimension (we'll get splits x splits number of fascias)
    :param subreg_sz: How many fascias per slab (subreg_sz x subreg_sz fascias per slab)
    :param x_offset: Slab offset from left
    :param y_offset: Slab offset from top
    :return: Box tuple suitable for pillow's Image.crop()
    """
    fascia_size = 256 // splits
    return (
        x_offset * fascia_size,
        y_offset * fascia_size,
        (x_offset + subreg_sz) * fascia_size,
        (y_offset + subreg_sz) * fascia_size,
    )


# Quarters: Split region into 2x2 Slabs and 2x2 Fascias (each Slab = 1x1 Fascias)
getbox_q = functools.partial(getbox, 2, 1)


# Ninths: Split region into 3x3 _overlapping_ Slabs
#         We first split the Region into 16x16 Fascias
#         Then each Slab is 6x6 Fascias
#         This gives 1-Fascia overlap between adjacent Slabs
getbox_n = functools.partial(getbox, 16, 6)


# For 5x5, use one of these strategies:
# n=5 c=52 b=1  gcd=1  ==> splits=256 sz=52 offset=51 (256x256 fascias, 52x52 fascia per slab, 52-51=1 fascia overlap)
# n=5 c=56 b=6  gcd=2  ==> splits=128 sz=28 offset=25 (128x128 ... 28x28 ... 28-25=3 ...)
# n=5 c=60 b=11 gcd=1  ==> splits=256 sz=60 offset=49 (256x256 ... 60x60 ... 60-49=11 ...)
# n=5 c=64 b=16 gcd=16 ==> splits=16  sz=4  offset=3  (16x16 ... 4x4 ... 4-3=1 ...)
#
# % overlap of above respectively: 1/52 ~~ 2%, 3/28 ~~ 10%, 11/60 ~~ 17%, 1/4 ~~ 25%

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
    Calculates the dominant colors of a Region and its Slabs.

    Currently hardcoded into calculating the dominant colors of the following:
    - The whole Region ("full")
    - Non-overlapping 2x2 Slabs ("quarters" or "q"s)
    - Slightly overlapping 3x3 Slabs ("ninths" or "n"s)

    For the 3x3 Slabs, the strategy is to first split the Region into 16x16 Fascias,
    then create 9 Slabs each of 6x6 Fascias. This will cause a 1-Fascia overlap between
    adjacent Slabs.

    All calculated dominant colors are stored in a dict with a label that describes its
    position in the Region.
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
        256: 3,  # full Region
        128: 2,  # quarter Region, size is 256 // 2
        96: 1,  # ninth Region, size is (256 // 16) * 6
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
        return getdom(im, qual)

    @classmethod
    def from_region(cls, region: MapRegion) -> DominantColors:
        imcopy = region.image.copy()
        domc = cls()
        for key in cls.CropBox.keys():
            # noinspection PyBroadException
            try:
                col = cls.calc_domc(imcopy, key)
            except Exception:
                if region.coord not in EMERGENCY_TRANSFORM:
                    print(f"get_color failure for {region.coord} {key}")
                    raise
                col = EMERGENCY_TRANSFORM[region.coord]
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
