# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import argparse
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, cast

import ruamel.yaml as ryaml

from sl_maptools import CoordType, RegionsDBRecord
from sl_maptools.utils import ConfigReader, make_backup

Config = ConfigReader("config.toml")


DEFA_DB = Path(Config.names.dir) / Config.names.db
SUPPORTED_SCHEMA_VERS = {"1.0.0"}


class InvalidSourceError(RuntimeError):
    pass


class OptionsType(Protocol):
    command: str
    db: Path
    to_yaml: Optional[Path]
    from_yaml: Optional[Path]


def get_options() -> OptionsType:
    parser = argparse.ArgumentParser(
        "retriever_v4.names.xchg", epilog="For more details, do COMMAND --help"
    )
    subparsers = parser.add_subparsers(title="COMMANDS", dest="command", required=True)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFA_DB,
        help=f"Path to the Regions DB pickle database. Defaults to {DEFA_DB}",
    )

    p_export = subparsers.add_parser("export", help="Export to YAML file")
    p_export.add_argument("to_yaml", type=Path, help="Target YAML file path")

    p_import_ = subparsers.add_parser("import", help="Import from YAML file")
    p_import_.add_argument("from_yaml", type=Path, help="Source YAML file path")

    _opts = parser.parse_args()
    return cast(OptionsType, _opts)


def export(db: Path, targ: Path, quiet: bool = False):
    with db.open("rb") as fin:
        data = pickle.load(fin)
    if not quiet:
        print(f"Retrieved {len(data)} records. Transforming...", end="", flush=True)

    result: dict[str, dict[str, Any]] = {}
    for coord, info in data.items():
        x, y = coord
        info["sources"] = sorted(info["sources"])
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
                ),
            },
        },
        "_metadata": {
            "created": datetime.now().astimezone().isoformat(timespec="minutes")
        },
        "data": result,
    }
    with targ.open("wt") as fout:
        ryaml.dump(exported, fout, default_flow_style=False)
    if not quiet:
        print(f"\nExported to {targ}")


def import_(src: Path, db: Path, quiet: bool = False):
    with src.open("rt") as fin:
        data = ryaml.safe_load(fin)

    if (_schema := data.get("_schema")) is None:
        raise InvalidSourceError("Source file does not have '_schema'")
    if _schema.get("name") != "sl-carto-regionsdb":
        raise InvalidSourceError(
            "Source file does not seem to be an exported RegionsDB!"
        )
    if (_ver := _schema.get("version")) not in SUPPORTED_SCHEMA_VERS:
        raise InvalidSourceError(f"Importer does not support schema version {_ver}")

    _metadata = data.get("_metadata")
    if not quiet:
        if _metadata:
            print(f"YAML file was created on {_metadata.get('created')}")
        else:
            print(f"YAML file does not have creation data.")

    regs_data: dict[str, dict[str, Any]]
    if (regs_data := data.get("data")) is None:
        raise InvalidSourceError("Source data does not contain data!")

    result: dict[CoordType, RegionsDBRecord] = {}
    if not quiet:
        print(
            f"{len(regs_data)} records retrieved. Transforming...", end="", flush=True
        )
    for scoord, coord_info in regs_data.items():
        coord = cast(CoordType, tuple(map(int, scoord.split(","))))
        coord_info["sources"] = set(coord_info["sources"])
        result[coord] = coord_info

    make_backup(db)
    with db.open("wb") as fout:
        pickle.dump(result, fout)

    if not quiet:
        print(f"\nImported to {db}")


def main(opts: OptionsType):
    if opts.command == "export":
        export(opts.db, opts.to_yaml)
    elif opts.command == "import":
        import_(opts.from_yaml, opts.db)
    else:
        raise ValueError(f"Unknown command: {opts.command}")


if __name__ == "__main__":
    options = get_options()
    main(options)
