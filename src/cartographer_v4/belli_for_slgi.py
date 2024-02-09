# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
from typing import NamedTuple, cast

from PIL import Image
from ruamel.yaml import YAML

from sl_maptools import AreaBounds, AreaBoundsSet, CoordType, inventorize_maps_latest
from sl_maptools.config import ConfigReader
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.validator import get_bonnie_coords

Config = ConfigReader("config.toml")

# language=yaml
BELLI_EXCLUSIONS_YAML = """
Atolls-FishermansTown:
    - 1023-1100/940-1023
    - 1034-1100/928-939

Victoria:
    - 1023-1100/928-939
    - 1037-1100/940-946
    - 1040-1100/947-949
    - 1044-1100/950-953
    - 1045-1100/954-957
    - 1044-1100/958-961
    - 1046-1100/962
    - 1047-1100/963-1023
    - 1023-1046/967-1023
    - 1023-1043/966
    - 1023-1042/965
    - 1023-1041/964
    - 1023-1040/963
    - 1023-1039/961-962
    - 1023-1037/960
    - 1023-1038/959
    - 1023-1039/954-958

Fantasseria:
    - 1023-1036/928-1023
    - 1037-1039/946-1023
    - 1040-1100/950-1023
    - 1054-1100/928-949
    - 1037-1100/928-929

BellisseriaForest:
    - 1023-1100/928-948
    - 1064-1100/928-1023
    - 1063/977-1023
    - 1023-1062/978-1023
    - 1050-1052/974-978
    - 1023-1045/964-1023
    - 1023-1044/963
    - 1023-1043/962
    - 1023-1042/949-961
    - 1042/949-960
    - 1043/955-956

OldBelli-ThePickles:
    - 1023-1100/928-953
    - 1040-1100/954-964
    - 1039/959
    - 1038-1039/960
    - 1043-1100/965
    - 1044-1100/966-969
    - 1047-1100/970-977
    - 1023-1100/978-1023
    
Ranchlands-Mediterranea:
    - 1023-1100/1001-1023
    - 1062-1100/928-1000
    - 1058-1061/928-989
    - 1045-1057/928-978
    - 1023-1044/928-977
    - 1023-1038/978-986
    - 1023-1034/987-1023
    - 1035-1049/999-1023

Stiltlands:
    - 1023-1100/928-966
    - 1023-1057/928-1023
    - 1057-1062/928-977
    - 1063/928-976
    - 1082-1100/928-1023
    - 1081/989
    - 1079-1081/990-1023
    - 1058-1078/994-1023
    - 1064-1072/992-993
    - 1068/991

Sakurasseria:
    - 1023-1100/1002-1023
    - 1023-1100/928-990
    - 1023-1061/991-1001
    - 1079-1100/991-1001
    - 1072-1077/991-992

Newbrooke-Alps:
    - 1023-1078/928-1023
    - 1079-1080/928-989
    - 1081-1100/928-985
    - 1088-1100/1015-1023
    - 1093-1100/1014
    - 1094-1100/1013

NewIslands:
    - 1023-1100/928-1011
    - 1087-1089/1012-1013
    - 1023-1086/1014-1023
    
"""


class Options(NamedTuple):
    """Represents options extracted from CLI"""

    overwrite: bool


def get_options() -> Options:
    """Get options from CLI"""
    parser = argparse.ArgumentParser()

    parser.add_argument("--overwrite", action="store_true", default=False)

    _opts = parser.parse_args()

    return cast(Options, _opts)


def main(opts: Options) -> None:  # noqa: D103
    belli_all = KNOWN_AREAS["Bellisseria_ALL"]
    belli_width = belli_all.bounding_box.width * 256
    belli_height = belli_all.bounding_box.height * 256
    belli_coords: set[CoordType] = set(xy for xy in belli_all.xy_iterator())

    bonnie_coords = get_bonnie_coords(Config.bonnie)
    map_tiles = inventorize_maps_latest(Config.maps.dir)

    with StringIO(BELLI_EXCLUSIONS_YAML) as fin:
        data: dict[str, list[str]] = YAML(typ="safe").load(fin)

    print("Creating base ... ", end="", flush=True)
    canvas_base = Image.new("RGBA", (belli_width, belli_height))
    img_tiles: dict[tuple[int, int], Image] = {}
    for xy in belli_coords:
        if xy not in map_tiles or xy not in bonnie_coords:
            continue
        x, y = xy
        canv_x = (x - belli_all.x_westmost) * 256
        canv_y = (belli_all.y_northmost - y) * 256
        with Image.open(map_tiles[x, y]) as img:
            img.load()
            img_tiles[x, y] = img.copy()
            img.putalpha(63)
            canvas_base.paste(img, (canv_x, canv_y))
    del img
    print(f"{len(img_tiles)} tiles", flush=True)

    westmost = belli_all.x_westmost
    nordmost = belli_all.y_northmost
    for mapname, excludes in data.items():
        targ: Path = Path(Config.areas.dir) / f"{mapname}.png"
        if not opts.overwrite and targ.exists():
            print(f"Skipping {mapname}")
            continue
        print(f"Generating {mapname} ... ", end="", flush=True)
        exc = AreaBoundsSet(AreaBounds.from_slgi(e) for e in excludes)
        canvas = canvas_base.copy()

        for xy in belli_coords:
            if xy not in img_tiles:
                continue
            if xy in exc:
                continue
            canv_x = (xy[0] - westmost) * 256
            canv_y = (nordmost - xy[1]) * 256
            canvas.paste(img_tiles[xy], (canv_x, canv_y))

        print(f"saving {targ} ... ", end="", flush=True)
        canvas.save(targ)
        print("done.", flush=True)
        del canvas


if __name__ == "__main__":
    main(get_options())
