# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import sys
from pathlib import Path
from pprint import PrettyPrinter

from cartographer.roadmapper.parse import bake, parse_stream
from cartographer.roadmapper.parse.config import options
from cartographer.roadmapper.yaml import save_to_yaml
from sl_maptools.utils import make_backup

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

    clean_routes = bake(all_recs, {})

    make_backup(output, levels=3)
    save_to_yaml(output, clean_routes)



if __name__ == '__main__':
    opts = options()
    main(**vars(opts))
