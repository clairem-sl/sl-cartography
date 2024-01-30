import pickle
from pathlib import Path

import ruamel.yaml

from sl_maptools import CoordType, RegionsDBRecord3
from sl_maptools.utils import ConfigReader, SLMapToolsConfig
from sl_maptools.validator import get_bonnie_coords

Config: SLMapToolsConfig = ConfigReader("config.toml")

OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def main():
    regionsdb = Path(Config.names.dir) / Config.names.db
    with regionsdb.open("rb") as fin:
        regsdb: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)
    valid_coords: set[CoordType] = {k for k, v in regsdb.items() if v["current_name"]}

    bonnie_coords = get_bonnie_coords(Config.bonnie)
    valid_coords.intersection_update(bonnie_coords)

    coordsets: list[set[CoordType]] = []
    for co in valid_coords:
        curset: set[CoordType] = {co}
        x, y = co
        for dx, dy in OFFSETS:
            tco = x + dx, y + dy
            if tco in valid_coords:
                curset.add(tco)
        if len(curset) > 1:
            coordsets.append(curset)

    combos: list[set[CoordType]]
    remove: list[int] = []
    prev_len: int = 0
    while prev_len != len(coordsets):
        prev_len = len(coordsets)
        print(prev_len, flush=True)
        combos = []
        while coordsets:
            curset: set[CoordType] = coordsets.pop()
            remove.clear()
            for i, one in enumerate(coordsets):
                if not curset.intersection(one):
                    continue
                curset.update(one)
                remove.append(i)
            combos.append(curset)
            for i in sorted(remove, reverse=True):
                del coordsets[i]
        coordsets = combos

    len_clumps: dict[int, list[set[CoordType]]] = {}
    for coset in coordsets:
        len_clumps.setdefault(len(coset), []).append(coset)

    for num in sorted(len_clumps):
        print(f"Clump of size {num} = {len(len_clumps[num])} areas")

    clumpsdb_p = Path(Config.names.dir) / "clumps.pkl"
    with clumpsdb_p.open("wb") as fout:
        pickle.dump(len_clumps, fout)
    print(f"Saved to {clumpsdb_p}")

    regions_areas = Path(Config.areas.dir) / "regions_areas.yaml"
    yaml = ruamel.yaml.YAML(typ="safe")
    with regions_areas.open("rt") as fin:
        regareas = yaml.load(fin)

    while True:
        print(sorted(len_clumps))
        inp = int(input("Len (0 to end) ? "))
        if inp == 0:
            break
        
        for i, coset in enumerate(len_clumps[inp], start=1):
            for co in coset:
                rn = regsdb[co]["current_name"]
                print(f"{i:2}) {co} {rn} [in {regareas.get(rn)}]")
            print("-" * 10)


if __name__ == "__main__":
    main()
