# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final, Protocol, cast

from PIL import Image

from cartographer_v4.lattice import LatticeMaker
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.validator import get_bonnie_coords, get_nonvoid_regions

DB_PATH: Final[Path] = Path(Config.names.dir) / Config.names.db
AREAMAPS_DIR: Final[Path] = Path(Config.areas.dir)


class Options(Protocol):
    """Options extracted from the CLI"""

    no_names: bool
    no_coords: bool
    areas: list[str]


def _get_options() -> Options:
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
    return cast(Options, _opts)


def main(opts: Options) -> None:  # noqa: D103
    # Disable DecompressionBombWarning
    Image.MAX_IMAGE_PIXELS = None

    areamaps_dir = Path(Config.areas.dir)

    regsdb = get_nonvoid_regions(Config.names)
    validation_set = set(regsdb) & get_bonnie_coords(Config.bonnie)

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
        want_areas = set(areamaps_dir.glob("*.png"))

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
    options = _get_options()
    main(options)
