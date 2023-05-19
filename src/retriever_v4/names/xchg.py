# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
from _operator import methodcaller

import packaging.version as versioning
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, cast, Final, TypedDict

from ruamel.yaml import YAML, RoundTripRepresenter

from retriever_v4.names.upgrade_db import upgrade_history_to_db3
from sl_maptools import (
    CoordType,
    RegionsDBRecord3,
)
from sl_maptools.utils import ConfigReader, make_backup

Config = ConfigReader("config.toml")


DEFA_DB = Path(Config.names.dir) / Config.names.db
DEFA_EXPORT = DEFA_DB.with_suffix(f".{datetime.now().strftime('%Y%m%d-%H%M')}.yaml")
SUPPORTED_SCHEMA_VERS: Final[set[int]] = {1, 3}


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
    p_export.add_argument(
        "to_yaml",
        metavar="YAML_file",
        type=Path,
        help=f"(Optional) Target YAML file path, defaults to {DEFA_EXPORT}",
        nargs="?",
        default=DEFA_EXPORT,
    )

    p_import_ = subparsers.add_parser("import", help="Import from YAML file")
    p_import_.add_argument("from_yaml", type=Path, help="Source YAML file path")

    _opts = parser.parse_args()
    return cast(OptionsType, _opts)


class RegionsDBRecord3ForSerialization(TypedDict):
    first_seen: str
    last_seen: str
    last_check: str
    current_name: str
    name_history3: dict[str, list[str]]
    sources: list[str]


def export(db: Path, targ: Path, quiet: bool = False):
    with db.open("rb") as fin:
        data: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)
    if not quiet:
        print(f"Retrieved {len(data)} records. Transforming...", end="", flush=True)

    iso_ts = methodcaller("isoformat", timespec="minutes")

    result: dict[str, RegionsDBRecord3ForSerialization] = {}
    for x, y in sorted(data, key=lambda co: (co[1], co[0])):
        info = data[x, y]
        result[f"{x},{y}"] = {
            "first_seen": iso_ts(info["first_seen"]),
            "last_seen": iso_ts(info["last_seen"]),
            "last_check": iso_ts(info["last_check"]),
            "current_name": info["current_name"],
            "name_history3": {
                name: [[iso_ts(ets), iso_ts(lts)] for ets, lts in tstamps]
                for name, tstamps in info["name_history3"].items()
            },
            "sources": sorted(info["sources"])
        }
    if not quiet:
        print("\nRecords transformed. Exporting...", end="", flush=True)

    exported = {
        "_schema": {
            "name": "sl-carto-regionsdb",
            "version": "3.0.0",
            "desc": {
                "_keys": "string representation of Coordinate Tuples in 'x,y' format",
                "current_name": "Current name of region as of time of audit",
                "first_seen": "Timestamp of audit when region was first detected (as non-void)",
                "last_check": "Timestamp of last audit when region was checked",
                "last_seen": "Timestamp of audit when region was last seen (as non-void)",
                "name_history": (
                    "A dict of name:[(timestamp pairs)], where each entry in the timestamps list is a pair of "
                    "timestamps (separated by tilde, comma, or space). The first timestamp represents the earliest "
                    "time the name is seen. The second represent the latest time the name is seen before changing."
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
    yaml = YAML(typ="safe")
    yaml.Representer = RoundTripRepresenter
    yaml.default_flow_style = False
    with targ.open("wt") as fout:
        yaml.dump(exported, fout)
    if not quiet:
        print(f"\nExported to {targ}")


def import_1(regs_data: dict[str, Any]) -> dict[CoordType, RegionsDBRecord3]:
    result: dict[CoordType, RegionsDBRecord3] = {}
    for scoord, data in regs_data.items():
        sco = scoord.split(",")
        coord: CoordType = int(sco[0]), int(sco[1])

        ser_hist: dict[str, list[str]] = data["name_history"]
        hist_old: dict[str, list[str]] = {
            name: [datetime.fromisoformat(ts) for ts in tstamps_s]
            for name, tstamps_s in ser_hist.items()
        }
        first_seen = datetime.fromisoformat(data["first_seen"])
        hist3 = upgrade_history_to_db3(first_seen, hist_old)

        result[coord] = {
            "current_name": cast(str, data["current_name"]),
            "first_seen": first_seen,
            "last_seen": datetime.fromisoformat(data["last_seen"]),
            "last_check": datetime.fromisoformat(data["last_check"]),
            "name_history3": hist3,
            "sources": set(data["sources"])
        }
    return result


def import_3(regs_data: dict[str, Any]) -> dict[CoordType, RegionsDBRecord3]:
    result: dict[CoordType, RegionsDBRecord3] = {}
    for scoord, data in regs_data.items():
        sco = scoord.split(",")
        coord: CoordType = int(sco[0]), int(sco[1])
        hist3: dict[str, list[tuple[datetime, datetime]]] = {}
        for name, tstamps in data["name_history3"].items():
            ts_list: list[tuple[datetime, datetime]] = []
            for ts in tstamps:
                t1, t2 = ts
                tr = datetime.fromisoformat(t1), datetime.fromisoformat(t2)
                ts_list.append(tr)
            hist3[name] = ts_list
        result[coord] = {
            "current_name": cast(str, data["current_name"]),
            "first_seen": datetime.fromisoformat(data["last_seen"]),
            "last_seen": datetime.fromisoformat(data["last_seen"]),
            "last_check": datetime.fromisoformat(data["last_check"]),
            "name_history3": hist3,
            "sources": set(data["sources"])
        }
    return result


def import_(src: Path, db: Path, quiet: bool = False):
    print(f"Reading {src} ...", end="", flush=True)
    yaml = YAML(typ="safe")
    with src.open("rt") as fin:
        data = yaml.load(fin)
    print("done.", flush=True)

    if (_schema := data.get("_schema")) is None:
        raise InvalidSourceError("Source file does not have '_schema'")
    if _schema.get("name") != "sl-carto-regionsdb":
        raise InvalidSourceError(
            "Source file does not seem to be an exported RegionsDB!"
        )
    _ver = versioning.parse(_schema.get("version", "0.0.0"))
    if _ver.major not in SUPPORTED_SCHEMA_VERS:
        raise InvalidSourceError(f"Schema version {_ver} not supported!")
    print(f"YAML file using schema version '{_ver}'")

    _metadata = data.get("_metadata")
    if not quiet:
        if _metadata:
            print(f"YAML file was created on {_metadata.get('created')}")
        else:
            print(f"YAML file does not have creation data.")

    regs_data: dict[str, dict[str, Any]]
    if (regs_data := data.get("data")) is None:
        raise InvalidSourceError("Source data does not contain data!")

    if not quiet:
        print(
            f"{len(regs_data)} records retrieved. Transforming...", end="", flush=True
        )
    result: dict[CoordType, RegionsDBRecord3] = {
        1: import_1,
        3: import_3,
    }[_ver.major](regs_data)

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
