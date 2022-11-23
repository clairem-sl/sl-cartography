# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import sys
from pathlib import Path
from pprint import PrettyPrinter

from cartographer.roadmapper.parse import bake, parse_stream
from cartographer.roadmapper.parse.config import options

DEBUG = False


def main(output: Path, recfiles: list[Path]):
    all_recs = []
    err = False
    for recfile in recfiles:
        if not recfile.exists():
            print(f"{recfile} not found!")
            sys.exit(1)
        print(f"Parsing {recfile}...")
        with recfile.open("rt", encoding="utf-8") as fin:
            err |= parse_stream(fin, all_recs)
    if err:
        print("Errors found. Please fix them first!")
        sys.exit(1)
    if DEBUG:
        pp = PrettyPrinter(width=160)
        pp.pprint(all_recs)

    bake(all_recs, {}, output)


if __name__ == '__main__':
    opts = options()
    main(**vars(opts))
