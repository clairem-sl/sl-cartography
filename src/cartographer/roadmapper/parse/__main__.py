# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import sys
from pathlib import Path
from pprint import PrettyPrinter

from cartographer.roadmapper.parse import bake, parse_stream
from cartographer.roadmapper.parse.config import options
from cartographer.roadmapper.yaml import save_to_yaml, load_from_yaml
from sl_maptools.utils import make_backup

DEBUG = False


def main(output: Path, recfiles: list[Path], merge_strategy: str):
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

    if not output.exists():
        save_to_yaml(output, clean_routes)
        return

    make_backup(output, levels=3)
    if merge_strategy == "overwrite":
        print("WARNING: --merge-strategy is 'overwrite', overwriting existing YAML file")
        save_to_yaml(output, clean_routes)
        return

    existing_routes = load_from_yaml(output)
    for conti, conti_routes in clean_routes.items():
        if conti not in existing_routes:
            existing_routes[conti] = conti_routes
            continue
        ex_conti_routes = existing_routes[conti]
        for route, route_vals in conti_routes:
            if route not in ex_conti_routes:
                ex_conti_routes[route] = route_vals
                continue
            if merge_strategy == 'update':
                ex_conti_routes[route] = route_vals
    save_to_yaml(output, clean_routes)


if __name__ == '__main__':
    opts = options()
    main(**vars(opts))
