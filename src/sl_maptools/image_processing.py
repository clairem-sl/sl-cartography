# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Self, TypedDict, cast

import numpy as np
from PIL import Image, ImageFilter
from skimage.metrics import (
    mean_squared_error as mse,
    normalized_root_mse as nrmse,
    structural_similarity as ssim,
)

BoxTuple = tuple[int, int, int, int]
RGBTuple = tuple[int, int, int]


def _gen_fascia(shift: int, size: int) -> list[BoxTuple]:
    # fmt: off
    return [
        (x, y, x + size, y + size)
        for x in range(0, 257 - shift, shift)
        for y in range(0, 257 - shift, shift)
    ]
    # fmt: on


FASCIA_COORDS: dict[int, list[BoxTuple]] = {
    1: [(0, 0, 256, 256)],
    2: _gen_fascia(128, 128),
    3: _gen_fascia(80, 96),
    4: _gen_fascia(64, 64),
    5: _gen_fascia(50, 56),
}
FASCIA_SIZES = sorted(FASCIA_COORDS.keys())


DEFA_KMEAN: int = 3
DEFA_KMEAN_DICT: dict[int, int] = {
    1: 5,
    2: 4,
    0: DEFA_KMEAN,  # Represents all others
}


def calculate_dominant_colors(
    region: Image.Image, fascia_per_side: int, kmeans: int | dict[int, int] | None = None
) -> list[RGBTuple]:
    """
    Given a region's image, calculate the dominant color per-fascia

    :param region: A 256x256 RGB(A) image representing a region
    :param fascia_per_side: How many fascias (per side) the image will be reduced to
    :param kmeans: The threshold for the K-Means quantization algorithm. Higher = slower, but more accurately
    reflecting the visual quantization.
    """
    if fascia_per_side not in FASCIA_COORDS:
        raise KeyError(f"Valid fascia_per_side values: {', '.join(map(str, FASCIA_SIZES))}")
    if kmeans is None:
        kmeans = DEFA_KMEAN_DICT
    if isinstance(kmeans, dict):
        kmeans = kmeans.get(fascia_per_side, kmeans.get(0, DEFA_KMEAN))
    dom_colors: list[RGBTuple] = []
    for fcoord in FASCIA_COORDS[fascia_per_side]:
        fascia = region.crop(fcoord)
        quant = fascia.quantize(colors=16, kmeans=kmeans)
        rgb = quant.convert("RGB")
        colors = cast(list[tuple[int, RGBTuple]], rgb.getcolors())
        freq, dom = max(colors, key=lambda x: x[0])
        dom_colors.append(dom)
    return dom_colors


class SimilarityThresholds(TypedDict):
    """Definition of Similarity Threshold fields"""

    mse: float
    ssim: float
    ssim_enh: float
    nrmse: float


DEFA_SIMILAR_THRESHOLDS: Final[SimilarityThresholds] = {
    "mse": 0.01,
    "ssim": 0.905,
    # "ssim_enh": 0.920,
    # "ssim_enh": 0.949,
    "ssim_enh": 0.955,
    "nrmse": 0.1,
}


@dataclass(slots=True, init=False, eq=False)
class SimilarityResult:
    """Records the result of similarity test, with a string that contains the justification"""

    similar: bool = False
    reason: str = ""
    values: list[float] = field(default_factory=list)

    def __bool__(self):
        return self.similar

    def append(self, val: float) -> None:
        """Append new value to the internal list"""
        self.values.append(val)

    def success(self, reason: str) -> Self:
        """Records a success (images considered similar)"""
        self.similar = True
        self.reason = reason
        return self

    def fail(self) -> Self:
        """Records a failure (images considered dissimilar)"""
        self.similar = False
        return self


def are_similar(image1: Image.Image, image2: Image.Image, thresholds: SimilarityThresholds = None) -> SimilarityResult:
    """
    Perform image similarity tests using mse, ssim, nrmse, and ssim with K values tuned by Wang et al

    :param image1: First image
    :param image2: Second image
    :param thresholds: Similarity thresholds
    """
    if thresholds is None:
        thresholds = DEFA_SIMILAR_THRESHOLDS
    result = SimilarityResult()
    with image1.convert("L") as im1, image2.convert("L") as im2:
        # noinspection PyTypeChecker
        im1_arr, im2_arr = np.asarray(im1), np.asarray(im2)
        result.append(_mse := mse(im1_arr, im2_arr))
        if _mse < thresholds["mse"]:
            return result.success("mse")
        result.append(_ssim := ssim(im1_arr, im2_arr))
        if _ssim > thresholds["ssim"]:
            return result.success("ssim")
        #
        result.append(_nrmse := nrmse(im1_arr, im2_arr))
        if _nrmse < thresholds["nrmse"]:
            return result.success("nrmse")
        # fmt: off
        im1_enh = (
            im1.filter(ImageFilter.GaussianBlur)
            .filter(ImageFilter.GaussianBlur)
            .filter(ImageFilter.FIND_EDGES)
        )
        im2_enh = (
            im2.filter(ImageFilter.GaussianBlur)
            .filter(ImageFilter.GaussianBlur)
            .filter(ImageFilter.FIND_EDGES)
        )
        # fmt: on
        # noinspection PyTypeChecker
        im1_arr, im2_arr = np.asarray(im1_enh), np.asarray(im2_enh)
        wangk = {
            "gaussian_weights": True,
            "sigma": 1.5,
            "use_sample_covariance": False,
            "K1": 0.02,
            "K2": 0.03,
        }
        # print(wangk)
        result.append(_ssim_e := ssim(im1_arr, im2_arr, **wangk))
        if _ssim_e > thresholds["ssim_enh"]:
            return result.success("ssim_enh")

    return result.fail()
