# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Final

# region Palettes
# Source: https://www.heavy.ai/blog/12-color-palettes-for-telling-better-stories-with-your-data
DUTCH_FIELD_WEB: Final = [
    "#e60049",
    "#0bb4ff",
    "#50e991",
    "#e6d800",
    "#9b19f5",
    "#ffa300",
    "#dc0ab4",
    "#b3d4ff",
    "#00bfa0",
]
RIVER_NIGHTS_WEB: Final = [
    "#b30000",
    "#7c1158",
    "#4421af",
    "#1a53ff",
    "#0d88e6",
    "#00b7c7",
    "#5ad45a",
    "#8be04e",
    "#ebdc78",
]
SPRING_PASTELS_WEB: Final = [
    "#fd7f6f",
    "#7eb0d5",
    "#b2e061",
    "#bd7ebe",
    "#ffb55a",
    "#ffee65",
    "#beb9db",
    "#fdcce5",
    "#8bd3c7",
]

# Source: https://colorbrewer2.org/#type=qualitative&scheme=Paired&n=10
BREWER_Q_10: Final = [
    (166, 206, 227),
    (31, 120, 180),
    (178, 223, 138),
    (51, 160, 44),
    (251, 154, 153),
    (227, 78, 84),  # I tripled the G and B part to make this not "too red"
    (253, 191, 111),
    (255, 127, 0),
    (202, 178, 214),
    (106, 61, 154),
]


def web_to_(web_hex: str) -> tuple[int, int, int]:
    return int(web_hex[1:3], 16), int(web_hex[3:5], 16), int(web_hex[5:7], 16)


PALETTES: Final[dict[str, dict[str, tuple[int, int, int]]]] = {
    "dutch_field": {f"dutch{n}": web_to_(c) for n, c in enumerate(DUTCH_FIELD_WEB, start=1)},
    "river_nights": {f"river{n}": web_to_(c) for n, c in enumerate(RIVER_NIGHTS_WEB, start=1)},
    "spring_pastels": {f"spring{n}": web_to_(c) for n, c in enumerate(SPRING_PASTELS_WEB, start=1)},
    "party_pastels": {  # Source: https://www.schemecolor.com/party-pastels.php
        "celadon": (182, 230, 189),  # Celadon, greenish
        "blupurp": (172, 154, 241),  # Maximum Blue Purple
        "rose": (247, 200, 238),  # Classic Rose
        "banana": (255, 239, 176),  # Banana Mania
        "tangerine": (245, 154, 142),  # Vivid Tangerine
    },
    "brewer_q_10": {f"bq10-{n}": c for n, c in enumerate(BREWER_Q_10, start=1)},
}
# endregion

AUTO_COLORS = PALETTES["brewer_q_10"]

RSVD_COLORS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "yellow": (255, 255, 0),
}

ALL_COLORS = AUTO_COLORS | RSVD_COLORS
