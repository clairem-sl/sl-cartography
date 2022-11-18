# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
from pathlib import Path

import appdirs

__all__ = ["STATE_DIR", "STATE_FILE_PATH", "NIGHTLIGHTS_NAME", "MOSAIC_NAME", "WORLD_WIDTH", "WORLD_HEIGHT", "options"]

STATE_DIR = Path(appdirs.site_data_dir("sl-cartography"))
STATE_FILE_PATH = STATE_DIR / "mosaic-state-v3.msgp"

WORKERS = 10

SAVE_DIR = Path(r"~\Pictures\SLMap").expanduser().absolute()
NIGHTLIGHTS_NAME = "world-nightlights-3.png"
MOSAIC_NAME = "world-mosaic-3-pil.png"

WORLD_WIDTH = 2001
WORLD_HEIGHT = 2001


def options():
    """
    Parse CLI options

    :return: A namespace containing the options
    """
    parser = argparse.ArgumentParser("SL Mosaic v3", formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("--xmin", type=int, default=0, help="Leftmost coordinate (inclusive)")
    parser.add_argument("--xmax", type=int, default=2000, help="Rightmost coordinate (inclusive)")
    parser.add_argument("--ymin", type=int, default=0, help="Bottommost coordinate (inclusive)")
    parser.add_argument("--ymax", type=int, default=2000, help="Topmost coordinate (inclusive)")

    parser.add_argument("--redo", type=str, default=None, help="Comma-separated rows to re-fetch")

    parser.add_argument("--savedir", type=Path, default=SAVE_DIR, help="Directory to save the PNG files")

    parser.add_argument("--workers", type=int, default=WORKERS, help="Number of TileProcessor workers")

    opts = parser.parse_args()

    if opts.redo is not None:
        _redo: str = str(opts.redo)
        opts.redo = list(map(int, _redo.split(",")))

    return opts
