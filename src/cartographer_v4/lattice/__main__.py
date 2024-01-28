# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import pickle
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

from PIL import Image

from cartographer_v4.lattice import LatticeMaker

if TYPE_CHECKING:
    from sl_maptools import CoordType, RegionsDBRecord3

from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords

Config: SLMapToolsConfig = ConfigReader("config.toml")

DB_PATH: Final[Path] = Path(Config.names.dir) / Config.names.db
AREAMAPS_DIR: Final[Path] = Path(Config.areas.dir)


class LatticeOptions(Protocol):
    """Options extracted from the CLI"""

    no_names: bool
    no_coords: bool
    areas: list[str]


def get_options() -> LatticeOptions:
    """Get options from CLI"""
    parser = argparse.ArgumentParser("cartographer_v4.lattice")

    parser.add_argument("--no-names", action="store_true", help="Don't add region names to the lattice")
    parser.add_argument("--no-coords", action="store_true", help="Don't add coordinates to the lattice")
    parser.add_argument(
        "--areas",
        metavar="AREA_LIST",
        type=str,
        nargs="+",
        help=(
            "Space- and/or comma-separated list of areas to retrieve, in addition to prior progress. "
            "If this option is specified, then make lattice for listed areas ONLY."
        ),
    )

    _opts = parser.parse_args()
    return cast(LatticeOptions, _opts)


def main(opts: LatticeOptions) -> None:  # noqa: D103
    # Disable DecompressionBombWarning
    Image.MAX_IMAGE_PIXELS = None

    areamaps_dir = Path(Config.areas.dir)

    validation_set: set[CoordType] = set()
    with DB_PATH.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)  # noqa: S301
    validation_set.update(k for k, v in regsdb.items() if v["current_name"])
    bonnie_coords = get_bonnie_coords(Config.bonnie)
    validation_set.intersection_update(bonnie_coords)

    want_areas: set[Path]
    if opts.areas:
        cs_anames = {k.casefold(): k for k in KNOWN_AREAS}
        # noinspection PyTypeChecker
        want_areas = {
            (areamaps_dir / cs_anames[a1]).with_suffix(".png")
            for area in opts.areas
            for a1 in map(str.casefold, area.split(","))
            if a1 in cs_anames
        }
    else:
        want_areas = {areamap for areamap in areamaps_dir.glob("*.png")}

    maker = LatticeMaker(
        regions_db=regsdb,
        validation_set=validation_set,
        out_dir=areamaps_dir,
    )

    tot = len(want_areas)
    for num, areamap in enumerate(want_areas, start=1):
        print(f"\n({num}/{tot}) {areamap.stem}", flush=True)
        maker.make_lattice(areamap)
    print()


if __name__ == "__main__":
    options = get_options()
    main(options)
