
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from pprint import pprint
from typing import NamedTuple

from ruamel.yaml import YAML

from sl_maptools import CoordType, RegionsDBRecord3, AreaBounds

DB_PATH = Path(r"C:\Cache\SL-Carto\RegionsDB3.pkl")
CUTOFF = 3

_NAO = datetime.now().astimezone()

DATABASE: dict[CoordType, RegionsDBRecord3] = {}


def main():
    global DATABASE

    with DB_PATH.open("rb") as fin:
        DATABASE.update(pickle.load(fin))

    region_locations: dict[str, set[CoordType]] = {}
    for co, data in DATABASE.items():
        if not data["current_name"]:
            continue
        if data["current_name"] == "Beorn City":
            print(data)
        region_locations.setdefault(data["current_name"], set()).add(co)
        for hname in data["name_history3"]:
            if not hname:
                continue
            region_locations.setdefault(hname, set()).add(co)

    for name, locs in sorted(region_locations.items()):
        if len(locs) < 2:
            continue
        print(f"{name}: {locs}")


if __name__ == '__main__':
    main()
