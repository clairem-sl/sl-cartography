# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import functools
from typing import Dict, Iterable, Tuple

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


class DominantColors:
    def __init__(self):
        self._domc: Dict[str, Tuple[int, int, int]] = {}

    def __getitem__(self, item):
        return self._domc[item]

    def __setitem__(self, key, value):
        self._domc[key] = value

    def __str__(self):
        return str(self._domc)

    @classmethod
    def from_tile(cls, tile: MapTile) -> DominantColors:
        def getbox(splits: int, subreg_sz: int, x_offset: int, y_offset: int):
            """
            Returns proper box tuple for image cropping

            :param splits: Split tile to how many subtile per dimension (we'll get splits x splits number of subtiles)
            :param subreg_sz: How many subtiles per subregion (subreg_sz x subreg_sz subtiles per subregion)
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

        imcopy = tile.image.copy()
        ims: Dict[str, Image.Image] = {
            "full": imcopy,
            "q_nw": imcopy.crop(getbox_q(0, 0)),
            "q_ne": imcopy.crop(getbox_q(0, 1)),
            "q_sw": imcopy.crop(getbox_q(1, 0)),
            "q_se": imcopy.crop(getbox_q(1, 1)),
            "n_nw": imcopy.crop(getbox_n(0, 0)),
            "n_no": imcopy.crop(getbox_n(5, 0)),
            "n_ne": imcopy.crop(getbox_n(10, 0)),
            "n_ea": imcopy.crop(getbox_n(0, 5)),
            "n_ce": imcopy.crop(getbox_n(5, 5)),
            "n_we": imcopy.crop(getbox_n(10, 5)),
            "n_sw": imcopy.crop(getbox_n(0, 10)),
            "n_so": imcopy.crop(getbox_n(5, 10)),
            "n_se": imcopy.crop(getbox_n(10, 10)),
        }
        qual_bysize = {
            256: 3,  # full tile
            128: 2,  # quarter tile, size is 256 // 2
            96: 1,  # ninth tile, size is (256 // 16) * 6
        }

        domc = cls()
        for k, im in ims.items():
            sz, _ = im.size
            qual = qual_bysize[sz]
            ct2 = ColorThief2(im)
            # noinspection PyBroadException
            try:
                col = ct2.get_color(qual)
            except Exception:
                if tile.coord not in EMERGENCY_TRANSFORM:
                    print(f"get_color failure for {tile.coord} {k}")
                    raise
                col = EMERGENCY_TRANSFORM[tile.coord]
            domc[k] = col

        return domc

    @classmethod
    def from_serialized(cls, raw_dict: Dict[str, Iterable[int]]):
        domc = cls()
        for k, v in raw_dict.items():
            domc[k] = tuple(v)
        return domc

    def encode(self):
        return self._domc

    def to_list(self, *indexes):
        return [self._domc[idx] for idx in indexes]