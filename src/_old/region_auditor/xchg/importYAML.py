# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle

import packaging.version as versioning
import ruamel.yaml as ryaml

from pathlib import Path
from typing import Any, cast

TupleIntInt = tuple[int, int]

DEFA_DB_PATH = Path(r"C:\Cache\SL-Carto\RegionsDB.pkl")


def get_options() -> argparse.Namespace:
    parser = argparse.ArgumentParser("importYAML")

    parser.add_argument(
        "--dbpath",
        type=Path,
        default=DEFA_DB_PATH,
        help=f"Path to database file. Defaults to {DEFA_DB_PATH}",
    )
    parser.add_argument(
        "--quiet", action="store_true", default=False, help="Process things silently"
    )
    parser.add_argument("yamlpath", type=Path, help="YAML file to import")

    _opts = parser.parse_args()

    return _opts


def import_yaml(yamlpath: Path, dbpath: Path, quiet: bool = False) -> None:
    result: dict[TupleIntInt, dict[str, Any]] = {}
    if not quiet:
        print(f"Reading YAML file {yamlpath} ... ", end="", flush=True)
    with yamlpath.open("rb") as fin:
        raw_data: dict[str, Any] = ryaml.safe_load(fin)
    if not quiet:
        print()
    if "_schema" not in raw_data:
        raise ValueError("Cannot find _schema")
    schema_version = versioning.parse(raw_data["_schema"].get("version", "0.0.0"))
    if schema_version.major != 1:
        raise ValueError("Schema is not version 1.x.x")
    data: dict[str, Any] = raw_data["data"]
    if not quiet:
        print(f"{len(data)} records retrieved.")
    coord: TupleIntInt
    if not quiet:
        print("Transforming YAML-encoded file into database ... ", end="", flush=True)
    for scoord, coord_data in data.items():
        assert isinstance(scoord, str)
        coord = cast(TupleIntInt, tuple(map(int, scoord.split(","))))
        result[coord] = coord_data
    with dbpath.open("wb") as fout:
        pickle.dump(result, fout, protocol=pickle.HIGHEST_PROTOCOL)
    if not quiet:
        print(f"\nDB stored as {dbpath}")


if __name__ == "__main__":
    options = get_options()
    import_yaml(**vars(options))
