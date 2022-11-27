# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import datetime
import sys
from pathlib import Path
from pprint import PrettyPrinter

from pytz import timezone

from cartographer.roadmapper.parse_chat import RE_TS, SLT_TIMEZONE, bake, parse_chat
from cartographer.roadmapper.parse_chat.config import options
from cartographer.roadmapper.yaml import load_from_yaml, save_to_yaml
from sl_maptools.utils import make_backup

DEBUG = False


def main(output: Path, recfiles: list[Path], merge_strategy: str, start_from: str):
    dt_start = None
    if start_from:
        if mm := RE_TS.match(start_from):
            dt_dict = {k: int(v) for k, v in mm.groupdict(0).items()}
            dt_start = datetime.datetime(**dt_dict, tzinfo=timezone(SLT_TIMEZONE))

    if output is None:
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output = Path(recfiles[0].name).with_suffix(f".{ts}.yaml")

    all_recs = []
    err = False
    for recfile in recfiles:
        if not recfile.exists():
            print(f"{recfile} not found!")
            sys.exit(1)
        print(f"Parsing {recfile}...")
        err |= parse_chat(recfile, all_recs, dt_start)
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
    print("Merge strategy is:", merge_strategy)

    existing_data = load_from_yaml(output)
    for conti, conti_routes in clean_routes.items():
        if conti not in existing_data:
            existing_data[conti] = conti_routes
            continue
        existing_routes = existing_data[conti]
        for route, segments in conti_routes.items():
            if route not in existing_routes:
                existing_routes[route] = segments
                continue
            if merge_strategy == "replace":
                existing_routes[route] = segments
                continue
            if merge_strategy == "append":
                existing_routes[route].extend(segments)
                continue
            # merge_strategy is 'update'
            ex_segments = existing_routes[route]
            ex_points_set = {s.points_as_tuple() for s in ex_segments}
            # add_segs = [seg for seg in segments if not seg.points_as_tuple() in ex_points_set]
            ex_segments.extend(seg for seg in segments if seg.points_as_tuple() not in ex_points_set)
    save_to_yaml(output, existing_data)


if __name__ == "__main__":
    opts = options()
    main(**vars(opts))
