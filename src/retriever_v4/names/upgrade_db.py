# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import operator
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from pprint import pprint
from typing import TYPE_CHECKING, Callable

from sl_maptools.utils import ConfigReader

if TYPE_CHECKING:
    from sl_maptools import CoordType, RegionsDBRecord, RegionsDBRecord3


Config = ConfigReader("config.toml")


def upgrade_history_to_db3(
        first_seen: datetime, hist_old: dict[str, list[str]]
) -> dict[str, list[tuple[datetime, datetime]]]:
    chronology: list[tuple[str, str]] = [(ts, aname) for aname, timestamps in hist_old.items() for ts in timestamps]
    chronology.sort(reverse=True)

    name_hist3: dict[str, list[tuple[datetime, datetime]]] = {}
    ts, aname = chronology.pop()
    end_dt = datetime.fromisoformat(ts)
    start_dt = first_seen
    name_hist3[aname] = [(start_dt, end_dt)]
    prev_end_dt = end_dt
    while chronology:
        ts, aname = chronology.pop()
        end_dt = datetime.fromisoformat(ts)
        delta = end_dt - prev_end_dt
        if delta.days < 1:
            delta /= 2
        else:
            delta = timedelta(days=1)
        start_dt = end_dt - delta
        name_hist3.setdefault(aname, []).append((start_dt, end_dt))
        prev_end_dt = end_dt

    return name_hist3


def upgrade_db_to_db3(db: dict[CoordType, RegionsDBRecord]) -> dict[CoordType, RegionsDBRecord3]:
    new_db: dict[CoordType, RegionsDBRecord3] = {}
    for coord, record in db.items():
        print(coord)

        first_seen: datetime = datetime.fromisoformat(record["first_seen"])
        new_db[coord] = {
            "first_seen": first_seen,
            "last_seen": datetime.fromisoformat(record["last_seen"]),
            "last_check": datetime.fromisoformat(record["last_check"]),
            "current_name": record["current_name"],
            "name_history3": upgrade_history_to_db3(first_seen, record["name_history"]),
            "sources": record["sources"],
        }

    return new_db


def main():
    db: dict[CoordType, RegionsDBRecord]
    db_path = Path(Config.names.dir) / "RegionsDB2.pkl"
    with db_path.open("rb") as fin:
        db = pickle.load(fin)

    new_db = upgrade_db_to_db3(db)
    iso_ts: Callable[[datetime], str] = operator.methodcaller("isoformat", timespec="minutes")
    for coord, record in new_db.items():
        for aname, timestamps in record["name_history3"].items():
            if len(timestamps) > 1:
                pprint({coord: {
                    "name": record["current_name"],
                    "first_seen": iso_ts(record["first_seen"]),
                    "last_seen": iso_ts(record["last_seen"]),
                    "last_check": iso_ts(record["last_check"]),
                    "history": {
                        aname: [f"{iso_ts(t1)}~{iso_ts(t2)}" for t1, t2 in tslist]
                        for aname, tslist in record["name_history3"].items()
                    },
                    "sources": record["sources"]
                }})

    # new_db_path = Path(Config.names.dir) / "RegionsDB3.pkl"
    # print(f"Saving to {new_db_path}")
    # with new_db_path.open("wb") as fout:
    #     pickle.dump(new_db, fout)
    # print("Done.")


if __name__ == "__main__":
    main()
