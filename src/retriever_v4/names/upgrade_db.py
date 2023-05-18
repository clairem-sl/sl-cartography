import pickle
from datetime import datetime, timedelta
from pathlib import Path

from sl_maptools import CoordType, RegionsDBRecord, RegionsDBRecord2
from sl_maptools.utils import ConfigReader

Config = ConfigReader("config.toml")


def main():
    db: dict[CoordType, RegionsDBRecord]
    db_path = Path(Config.names.dir) / Config.names.db
    with db_path.open("rb") as fin:
        db = pickle.load(fin)

    new_db: dict[CoordType, RegionsDBRecord2] = {}
    for coord, record in db.items():
        print(coord)
        chronology: list[tuple[str, str]] = []
        for aname, timestamps in record["name_history"].items():
            for ts in timestamps:
                chronology.append((ts, aname))
        chronology.sort(reverse=True)

        name_hist2: dict[str, list[tuple[datetime, datetime]]] = {}
        ts, aname = chronology.pop()
        end_dt = datetime.fromisoformat(ts)
        start_dt = datetime.fromisoformat(record["first_seen"])
        name_hist2[aname] = [(start_dt, end_dt)]
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
            name_hist2.setdefault(aname, []).append((start_dt, end_dt))
            prev_end_dt = end_dt
        new_db[coord] = {
            "first_seen": datetime.fromisoformat(record["first_seen"]),
            "last_seen": datetime.fromisoformat(record["last_seen"]),
            "last_check": datetime.fromisoformat(record["last_check"]),
            "current_name": record["current_name"],
            "name_history2": name_hist2,
            "sources": record["sources"],
        }

    new_db_path = Path(Config.names.dir) / "RegionsDB3.pkl"
    print(f"Saving to {new_db_path}")
    with new_db_path.open("wb") as fout:
        pickle.dump(new_db, fout)
    print("Done.")


if __name__ == "__main__":
    main()
