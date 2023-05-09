# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import pickle

import ruamel.yaml as ryaml

from datetime import datetime
from pathlib import Path
from pprint import pprint
from typing import Any


DB_PATH = Path(r"C:\Cache\SL-Carto\RegionsDB2.pkl")


def export(db_path: Path, quiet: bool = False) -> Path:
    result: dict[str, dict[str, Any]] = {}
    with db_path.open("rb") as fin:
        data: dict[tuple[int, int], dict[str, Any]] = pickle.load(fin)
    if not quiet:
        print(f"Retrieved {len(data)} records. Transforming...", end="", flush=True)
    for coord, info in data.items():
        x, y = coord
        info["sources"] = list(info["sources"])
        result[f"{x},{y}"] = info

    if not quiet:
        print("\nRecords transformed. Exporting...", end="", flush=True)
    exported = {
        "_schema": {
            "name": "sl-carto-regionsdb",
            "version": "1.0.0",
            "desc": {
                "current_name": "Current name of region as of time of audit",
                "first_seen": "Timestamp of audit when region was first detected (as non-void)",
                "last_check": "Timestamp of last audit when region was checked",
                "last_seen": "Timestamp of audit when region was last seen (as non-void)",
                "name_history": (
                    "A dict of name:[timestamps], where each entry in the timestamps list is timestamp of "
                    "last audit when region was detected using that name. This enables proper chronology in the "
                    "rare but possible situation of a region going Name1->Name2->Name1."
                ),
                "sources": (
                    "Sources of information used to generate the record. 'cap' is SL's cap server. "
                    "'bb' is BonnieBots database."
                )
            }
        },
        "_metadata": {
            "created": datetime.now().astimezone().isoformat(timespec="minutes")
        },
        "data": result
    }
    yml_path = DB_PATH.with_suffix(".yaml")
    with yml_path.open("wt") as fout:
        ryaml.dump(exported, fout, default_flow_style=False)

    if not quiet:
        print(f"\nExported to {yml_path}")
    # with yml_path.open("rt") as fin:
    #     print(fin.read())

    return yml_path


def main():
    export(DB_PATH)


if __name__ == '__main__':
    main()
