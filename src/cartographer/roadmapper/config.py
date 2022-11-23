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
        "SL RoadMapper", epilog="You must specify either one (or several) YAML_FILE(s), or `--readchat CHAT_FILE`"
    )

    parser.add_argument(
        "--saveto",
        metavar="YAML_FILE",
        type=Path,
        help="If specified, save a YAML representation of the routes into YAML_FILE",
    )

    parser.add_argument("--readchat", metavar="CHAT_FILE", type=Path, nargs="+", help="If specified, parse chat files")

    parser.add_argument(
        "yamlfiles",
        metavar="YAML_FILE",
        type=Path,
        nargs="*",
        help="One (or more) YAML files",
    )

    opts = parser.parse_args()
    if not opts.readchat and not opts.yamlfiles:
        raise RuntimeError("Please specify YAML_FILE(s) or use `--readchat CHAT_FILE`!")

    return opts
