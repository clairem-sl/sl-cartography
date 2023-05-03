# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import httpx
import ruamel.yaml as ryaml

from pathlib import Path
from typing import Final


BONNIE_REGDB_URL: Final[str] = "https://www.bonniebots.com/static-api/regions/index.json"


def get_bonnie_coords(bonniedb: Path, fetchbonnie: bool) -> set[tuple[int, int]]:
    bdb_data_raw = {}
    if bonniedb:
        print(f"Reading BonnieBots Regions DB from {bonniedb} ... ", end="", flush=True)
        with bonniedb.open("rb") as fin:
            bdb_data_raw = ryaml.safe_load(fin)
    elif fetchbonnie:
        print(f"Fetching BonnieBots Regions DB ... ", end="", flush=True)
        with httpx.Client(timeout=10) as client:
            resp = client.get(BONNIE_REGDB_URL)
            bdb_data_raw = resp.json()
    return {
        (int(record["region_x"]), int(record["region_y"]))
        for record in bdb_data_raw["regions"]
    }
