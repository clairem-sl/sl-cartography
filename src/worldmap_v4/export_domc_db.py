import pickle
from pathlib import Path
from typing import Final

from ruamel.yaml import YAML, RoundTripRepresenter

from sl_maptools import CoordType
from sl_maptools.config import DefaultConfig as Config


DOMC_DB_PATH: Final[Path] = Path(Config.mosaic.dir) / Config.mosaic.domc_db


def main():
    print("Reading DB")
    with DOMC_DB_PATH.open("rb") as fin:
        domc_db: dict[CoordType, dict[Path, dict[int, list]]] = pickle.load(fin)

    print("Transform DB")
    out_db: dict[str, dict[str, dict[int, list]]] = {}
    for co, data in sorted(domc_db.items(), key=lambda i: (i[0][1], i[0][0])):
        inner = {}
        for fp, domc in sorted(data.items()):
            inner[str(fp)] = domc
        x, y = co
        out_db[f"{x},{y}"] = inner

    print("Writing YAML")
    yaml = YAML(typ="safe")
    yaml.Representer = RoundTripRepresenter
    with DOMC_DB_PATH.with_suffix(".yaml").open("wt") as fout:
        yaml.dump(out_db, fout)

    print("Done.")


if __name__ == '__main__':
    main()
