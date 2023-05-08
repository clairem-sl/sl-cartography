from typing import cast

from PIL import Image

BoxTuple = tuple[int, int, int, int]
RGBTuple = tuple[int, int, int]

FASCIA_COORDS: dict[int, list[BoxTuple]] = {
    1: [(0, 0, 256, 256)],
    2: [(0, 0, 128, 128), (0, 128, 128, 256), (128, 0, 256, 128), (128, 128, 256, 256)],
    3: [
        (0, 0, 96, 96),
        (0, 80, 96, 176),
        (0, 160, 96, 256),
        (80, 0, 176, 96),
        (80, 80, 176, 176),
        (80, 160, 176, 256),
        (160, 0, 256, 96),
        (160, 80, 256, 176),
        (160, 160, 256, 256),
    ],
    4: [
        (0, 0, 64, 64),
        (0, 64, 64, 128),
        (0, 128, 64, 192),
        (0, 192, 64, 256),
        (64, 0, 128, 64),
        (64, 64, 128, 128),
        (64, 128, 128, 192),
        (64, 192, 128, 256),
        (128, 0, 192, 64),
        (128, 64, 192, 128),
        (128, 128, 192, 192),
        (128, 192, 192, 256),
        (192, 0, 256, 64),
        (192, 64, 256, 128),
        (192, 128, 256, 192),
        (192, 192, 256, 256),
    ],
    5: [
        (0, 0, 56, 56),
        (0, 50, 56, 106),
        (0, 100, 56, 156),
        (0, 150, 56, 206),
        (0, 200, 56, 256),
        (50, 0, 106, 56),
        (50, 50, 106, 106),
        (50, 100, 106, 156),
        (50, 150, 106, 206),
        (50, 200, 106, 256),
        (100, 0, 156, 56),
        (100, 50, 156, 106),
        (100, 100, 156, 156),
        (100, 150, 156, 206),
        (100, 200, 156, 256),
        (150, 0, 206, 56),
        (150, 50, 206, 106),
        (150, 100, 206, 156),
        (150, 150, 206, 206),
        (150, 200, 206, 256),
        (200, 0, 256, 56),
        (200, 50, 256, 106),
        (200, 100, 256, 156),
        (200, 150, 256, 206),
        (200, 200, 256, 256),
    ],
}
FASCIA_SIZES = sorted(FASCIA_COORDS.keys())


def calculate_dominant_colors(region: Image.Image, fascia_per_side: int, kmeans: int = 3) -> list[RGBTuple]:
    if fascia_per_side not in FASCIA_COORDS:
        raise KeyError(f"Valid fascia_per_side values: {', '.join(map(str, FASCIA_SIZES))}")
    dom_colors: list[RGBTuple] = []
    for fcoord in FASCIA_COORDS[fascia_per_side]:
        fascia = region.crop(fcoord)
        quant = fascia.quantize(colors=16, kmeans=kmeans)
        rgb = quant.convert("RGB")
        colors = cast(list[tuple[int, RGBTuple]], rgb.getcolors())
        freq, dom = max(colors, key=lambda x: x[0])
        dom_colors.append(dom)
    return dom_colors
