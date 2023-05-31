from datetime import datetime
import pickle
from pathlib import Path
from pprint import pprint
from typing import Any, TypedDict

import httpx

from sl_maptools import CoordType


BONNIE_RAW = "BonnieRaw.pkl"
BONNIE_BY_COORD = "BonnieByCoord.pkl"
BONNIE_DETAILS_BY_COORD = "BonnieDetailsByCoord.pkl"


class BonnieMeta(TypedDict):
    current: dict[str,Any]
    diff: dict[datetime, dict[str, Any]]


det_by_co: dict[CoordType, BonnieMeta] = {}


def update_bonniedata(x: int, y: int, curdata: dict):
    global det_by_co

    _nao = datetime.now().astimezone()
    _co = x, y
    if _co not in det_by_co:
        det_by_co[_co] = {
            "current": curdata,
            "diff": {}
        }
        return
    prev = det_by_co[_co]["current"]
    det_by_co[_co]["current"] = curdata
    prev_diff = {}
    for k, v in prev.items():
        if k not in curdata:
            prev_diff[k] = v
            continue
        if v != curdata[k]:
            prev_diff[k] = v
            continue
    if prev_diff:
        det_by_co[_co]["diff"][_nao] = prev_diff


def main():
    global det_by_co

    with httpx.Client() as client:
        resp_all = client.get("https://www.bonniebots.com/static-api/regions/index.json")
        all_data = resp_all.json()
        fp = Path(BONNIE_RAW)
        with fp.open("wb") as fout:
            pickle.dump(all_data, fout)

    by_coord: dict[CoordType, set[str]] = {}
    for regdata in all_data["regions"]:
        _co = int(regdata["region_x"]), int(regdata["region_y"])
        by_coord.setdefault(_co, set()).add(regdata["region_name"])
    with Path(BONNIE_BY_COORD).open("wb") as fout:
        pickle.dump(by_coord, fout)

    fp = Path(BONNIE_DETAILS_BY_COORD)
    if fp.exists():
        with fp.open("rb") as fin:
            det_by_co = pickle.load(fin)

    want_co: set[CoordType] = {
        (int(regdata["region_x"]), int(regdata["region_y"]))
        for regdata in all_data["regions"]
    }

    try:
        with httpx.Client(http2=True) as client:
            for i, (x, y) in enumerate(want_co, start=1):
                print(f"{x},{y}", end="  ", flush=True)
                resp = client.get(f"https://www.bonniebots.com/static-api/regions/{x}/{y}/index.json")
                update_bonniedata(x, y, resp.json())
                if (i % 10) == 0:
                    with fp.open("wb") as fout:
                        pickle.dump(det_by_co, fout)
    except KeyboardInterrupt:
        print("User Interrupted")

    pprint(det_by_co)

    with fp.open("wb") as fout:
        pickle.dump(det_by_co, fout)

"""
{"region_name":"Blake Sea - Turnbuckle","region_map_image":"c0bb2964-af2c-0c2a-27bb-dd36aac5ba3b","region_x":1133,"region_y":1049,"region_owner":"00000000-0000-0000-0000-000000000000","region_product_sku":"129","region_product_name":"Mainland / Homestead","estate_id":1,"hard_max_agents":25,"hard_max_objects":5000,"deny_age_unverified":false,"region_access":21,"deleted_at":null,"estate_name":"mainland","region_ip":"35.87.7.207","region_port":13055,"channel_version":"Second Life Server 2023-05-05.579955","region_updated_at":"2023-05-29T05:17:13.336Z","access_name":"Moderate"}
"""


if __name__ == '__main__':
    main()
