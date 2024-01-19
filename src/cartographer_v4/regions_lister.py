# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import pickle
from pathlib import Path
from typing import Final

from ruamel.yaml import YAML, RoundTripRepresenter

from sl_maptools import CoordType, RegionsDBRecord3
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.utils import ConfigReader, SLMapToolsConfig

Config: SLMapToolsConfig = ConfigReader("config.toml")

DB_PATH: Final[Path] = Path(Config.names.dir) / Config.names.db
LIST_PATH: Final[Path] = Path(Config.areas.dir)


def main():
    with DB_PATH.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)  # noqa: S301

    r_a: dict[str, list[str]] = {}

    c = 0
    for area_name, area_desc in KNOWN_AREAS.items():
        for xy in area_desc.xy_iterator():
            if xy not in regsdb:
                continue
            reg_data = regsdb[xy]
            if not reg_data.get("current_name"):
                continue
            r_a.setdefault(reg_data["current_name"], []).append(area_name)
            c += 1
            if (c % 1000) == 0:
                print(".", end="", flush=True)
    print()

    regions_areas: dict[str, list[str]] = dict.fromkeys(sorted(r_a, key=lambda s: s.casefold()))
    for a in regions_areas:
        regions_areas[a] = sorted(set(r_a[a]))
    print(f"{len(regions_areas):_} regions have been mapped")

    targ = LIST_PATH / "regions_areas.yaml"
    yaml = YAML(typ="safe")
    yaml.Representer = RoundTripRepresenter
    yaml.default_flow_style = False
    with targ.open("wt") as fout:
        yaml.dump(regions_areas, fout)
    print(f"Saved to {targ}")


if __name__ == "__main__":
    main()
