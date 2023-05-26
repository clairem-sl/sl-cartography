
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from pprint import pprint

from sl_maptools import CoordType, RegionsDBRecord3, AreaBounds

DB_PATH = Path(r"C:\Cache\SL-Carto\RegionsDB3.pkl")
CUTOFF = 3


def main():
    with DB_PATH.open("rb") as fin:
        db: dict[CoordType, RegionsDBRecord3] = pickle.load(fin)

    nao = datetime.now().astimezone()
    interesting: list[tuple[datetime, str, CoordType]] = []
    for co, data in db.items():
        delta = nao - data["first_seen"]
        if delta.days < CUTOFF:
            d = data["first_seen"], data["current_name"], co
            interesting.append(d)

    interesting.sort()
    print(f"{len(interesting)} new regions the past {CUTOFF} days")
    new_areas: dict[str, list[CoordType]] = {}
    for i, (t, name, co) in enumerate(interesting, start=1):
        print(f"{i:>3}) {t.isoformat(timespec='minutes')} {name} {co}")
        if name.startswith("RFL"):
            new_areas.setdefault("RFL", []).append(co)
        elif name.startswith("SLB"):
            new_areas.setdefault("SLB", []).append(co)

    print()
    print(f"RFL => {AreaBounds.from_coordset(new_areas['RFL'])!r}")
    print(f"SLB => {AreaBounds.from_coordset(new_areas['SLB'])!r}")


if __name__ == '__main__':
    main()
