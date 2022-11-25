# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import textwrap
from pathlib import Path

import appdirs

STATE_DIR = Path(appdirs.site_data_dir("sl-cartography"))
STATE_FILE_NAME = "roadmapper.msgp"


SAVE_DIR = Path(r"~\Pictures\SLMap\Carto").expanduser().absolute()


def options():
    """
    Parse CLI options

    :return: A namespace containing the options
    """

    epilog = textwrap.dedent("""
    WARNING: The granularity for --merge-strategy is per named route (that is, Continent::RoadName).
    If you are doing a piecemeal roadmapping of a route, e.g., say the grids of Bay City, you MUST
    finish the whole route first. If not, then later segments will overwrite the earlier segments
    and you will lose your earlier records _for_that_route_.
    """)

    parser = argparse.ArgumentParser("parse", epilog=epilog)

    parser.add_argument(
        "--merge-strategy", "-m",
        metavar="STRATEGY",
        choices=["overwrite", "update", "insert"],
        default="update",
        help=(
            "Strategy to use if there's already existing YAML file. "
            "'overwrite' means the file will be overwritten (DANGER! Might cause routes to be lost!), "
            "'update' (default) means existing routes will have their points updated (if there "
            "are any updates) and new routes added, "
            "'insert' means only new routes will be added and existing routes will be untouched."
        )
    )

    parser.add_argument(
        "--start-from", "-s",
        metavar="TIMESTAMP",
        help=(
            "An ISO8601-like timestamp. Parsing of chat files will begin only from this timestamp (inclusive). "
            "These are valid formats: 2022-11-22 16:53, 2022/11/22 02:53, 2022-11-22T02:53"
        )
    )

    parser.add_argument(
        "--output",
        "-o",
        metavar="YAML_FILE",
        type=Path,
        help=(
            "Save YAML representation in the specified yaml file. If not specified, a name based on the FIRST chat "
            "transcript file will be used."
        ),
    )

    parser.add_argument(
        "recfiles",
        metavar="FILE",
        type=Path,
        nargs="+",
        help="One (or more) chat transcript files",
    )

    opts = parser.parse_args()

    return opts
