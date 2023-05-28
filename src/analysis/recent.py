
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from pprint import pprint
from typing import NamedTuple

from sl_maptools import CoordType, RegionsDBRecord3, AreaBounds

DB_PATH = Path(r"C:\Cache\SL-Carto\RegionsDB3.pkl")
CUTOFF = 3

_NAO = datetime.now().astimezone()

DATABASE: dict[CoordType, RegionsDBRecord3]


class InterestingRegion(NamedTuple):
    timestamp: datetime
    name: str
    coord: CoordType


def recent(max_days: int) -> set[InterestingRegion]:
    result: set[InterestingRegion] = set()
    for co, data in DATABASE.items():
        delta = _NAO - data["first_seen"]
        if delta.days <= max_days:
            d = InterestingRegion(data["first_seen"], data["current_name"], co)
            result.add(d)
    return result


def main():
    global DATABASE

    with DB_PATH.open("rb") as fin:
        DATABASE = pickle.load(fin)

    interesting: list[InterestingRegion] = sorted(recent(CUTOFF))
    print(f"{len(interesting)} new regions the past {CUTOFF} days")
    new_areas: dict[str, list[CoordType]] = {}
    for i, (t, name, co) in enumerate(interesting, start=1):
        print(f"{i:>3}) {t.isoformat(timespec='minutes')} {name} {co}")


if __name__ == '__main__':
    main()
