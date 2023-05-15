
import argparse

from pathlib import Path
from typing import cast, Protocol


class OptionsType(Protocol):
    command: str
    dbdir: Path
    yaml_file: Path


def get_options() -> OptionsType:
    parser = argparse.ArgumentParser("retriever_v4.names.xchg", epilog="For more details, do COMMAND --help")
    subparsers = parser.add_subparsers(title="COMMANDS", dest="command", required=True)
    # parser.add_argument("--dbdir", type=Path)
    # parser.add_argument("yaml_file", type=Path)

    export = subparsers.add_parser("export", help="Export to YAML file")
    export.add_argument("from_db", type=Path)
    export.add_argument("to_yaml", type=Path)

    import_ = subparsers.add_parser("import", help="Import from YAML file")
    import_.add_argument("from_yaml", type=Path)
    import_.add_argument("to_db", type=Path)

    _opts = parser.parse_args()
    return cast(OptionsType, _opts)


def main(opts: OptionsType):
    ...


if __name__ == "__main__":
    options = get_options()
    main(options)
