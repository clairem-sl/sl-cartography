# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
from pathlib import Path

import appdirs


SAVE_DIR = Path(r"~\Pictures\SLMap\Carto").expanduser().absolute()


def options():
    """
    Parse CLI options

    :return: A namespace containing the options
    """
    parser = argparse.ArgumentParser(
        "SL Mosaic v3", epilog="You must specify either one (or several) FILE(s), or `--readfrom YAML_FILE`"
    )

    parser.add_argument(
        "--saveto",
        metavar="YAML_FILE",
        type=Path,
        help="If specified, save a YAML representation of the routes into YAML_FILE",
    )

    parser.add_argument(
        "--readfrom", metavar="YAML_FILE", type=Path, help="If specified, read road data from YAML_FILE"
    )

    parser.add_argument(
        "recfiles",
        metavar="FILE",
        type=Path,
        nargs="*",
        help="One (or more) chat transcript files",
    )

    opts = parser.parse_args()
    if not opts.recfiles and not opts.readfrom:
        raise RuntimeError("Please specify FILE(s) or use `--readfrom YAML_FILE`!")

    return opts
