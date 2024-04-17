# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import time
from asyncio import Task
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn, TypedDict

import httpx
from ruamel.yaml import YAML, RoundTripRepresenter

from retriever_v4 import ProgressInterface, dispatch_fetcher
from sl_maptools import CoordType, MapCoord
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.fetchers.bonnie import BoundedBonnieFetcher, CookedBonnieResult
from sl_maptools.utils import make_backup
from sl_maptools.validator import get_bonnie_coords

if TYPE_CHECKING:
    from collections.abc import Generator

CONN_LIMIT: Final[int] = 400
HTTP2: Final[bool] = False
ACCEPTABLE_STATUSCODES: Final[set[int]] = {200, 403}


AbortRequested = asyncio.Event()


class BonnieRegionPointers(TypedDict):
    """Represents data extracted from BonnieBots DB"""

    region_name: str
    region_x: int
    region_y: int


class BonnieRegionDetails(TypedDict):
    """Represents detailed data extracted from BonnieBots DB"""

    region_name: str
    region_map_image: str
    region_x: int
    region_y: int
    region_owner: str
    region_product_sku: str
    region_product_name: str
    estate_id: int
    hard_max_agents: int
    hard_max_objects: int
    deny_age_unverified: bool
    region_access: int
    deleted_at: str | None
    estate_name: str
    region_ip: str
    region_port: int
    channel_version: str
    region_updated_at: str
    access_name: str


class BonnieRegionsAll(TypedDict):
    """Represents complete dump of BonnieBots DB"""

    updated: int
    regions: list[BonnieRegionPointers]


class BonnieMeta(TypedDict):
    """Represents metadata about BonnieBots DB"""

    current: dict[str, Any]
    last_update: datetime
    diff: dict[datetime, dict[str, Any]]


BonnieDetailsDB: dict[CoordType, BonnieMeta] = {}


class BonnieProgress:
    """Tracks progress of BonnieBots retrieval"""

    def __init__(self):
        """No parameters"""
        at_end: set[tuple[datetime, CoordType]] = set()
        at_beginning: set[CoordType] = set()
        for co in get_bonnie_coords(Config.bonnie):
            # Prioritize coordinates not yet in DB
            if co not in BonnieDetailsDB:
                at_beginning.add(co)
            else:
                # Record last_update as well so we can sort by datapoint age
                last_update = BonnieDetailsDB[co]["last_update"]
                try:
                    if last_update.tzinfo is None or last_update.tzinfo.utcoffset(last_update) is None:
                        print(f"Existing last_update for {co} is naive")
                        last_update = last_update.astimezone()
                except AttributeError:
                    print(f"Malformed data for [{co}]")
                    raise
                at_end.add((last_update, co))
        self._to_fetch: deque[CoordType] = deque(at_beginning)
        # Prioritize oldest datapoints. Oldest = smallest timestamp of course
        self._to_fetch.extend(co for _, co in sorted(at_end))

        self._outstanding: set[CoordType] = set()

    @property
    def next_coordinate(self) -> CoordType:
        """The next coordinate to fetch, without actually moving forward the iterator"""
        return self._to_fetch[0]

    @property
    def outstanding_count(self) -> int:
        """The number of retrieval jobs still outstanding"""
        return len(self._outstanding)

    @property
    def total_to_fetch(self) -> int:
        """The number of retrieval jobs in total"""
        return len(self._to_fetch)

    async def abatch(self, batch_size: int) -> Generator[CoordType, None, None]:
        """Asynchronous generator of a batch"""
        for _ in range(batch_size):
            if not self._to_fetch:
                return
            coord = self._to_fetch.popleft()
            self._outstanding.add(coord)
            yield coord

    def retire(self, item: CoordType) -> None:
        """Retires a retrieval job (remove it from list of outstanding jobs)"""
        self._outstanding.discard(item)

    def save(self) -> NoReturn:
        """Save progress to file -- NOT IMPLEMENTED"""
        pass


Progress: ProgressInterface


def update_bonniedata(result: CookedBonnieResult) -> bool:
    """
    Perfom update on the local copy of BonnieBots DB

    :return: True if there are changes, False otherwise
    """
    (x, y), curdata, _ = result
    _co = x, y
    _nao = datetime.now().astimezone()
    if _co not in BonnieDetailsDB:
        BonnieDetailsDB[_co] = {"current": curdata, "last_update": _nao, "diff": {}}
        return True
    prev = BonnieDetailsDB[_co]["current"]
    BonnieDetailsDB[_co]["current"] = curdata
    BonnieDetailsDB[_co]["last_update"] = _nao
    prev_diff = {}
    for k, v in prev.items():
        if k not in curdata:
            prev_diff[k] = v
            continue
        if v != curdata[k]:
            prev_diff[k] = v
            continue
    if prev_diff:
        BonnieDetailsDB[_co]["diff"][_nao] = prev_diff
        return True
    return False


async def amain(duration: int, min_batch_size: int, abort_low_rps: int) -> None:  # noqa: D103
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=HTTP2) as client:
        fetcher = BoundedBonnieFetcher(CONN_LIMIT * 3, client, cancel_flag=AbortRequested, cooked=True)
        shown = False

        def make_task(coord: CoordType) -> Task:
            return asyncio.create_task(fetcher.async_fetch(MapCoord(*coord)), name=str(coord))

        def pre_batch() -> None:
            nonlocal shown
            shown = False

        def process_result(fut_result: CookedBonnieResult | None) -> bool:
            nonlocal shown
            if fut_result is None:
                return False
            if fut_result.status_code not in ACCEPTABLE_STATUSCODES:
                return False
            if fut_result.result and not shown:
                shown = True
                print("🌐", end="")
                # print(
                #     f'({fut_result.coord.x},{fut_result.coord.y})',
                #     end="",
                #     flush=True,
                # )
            return update_bonniedata(fut_result)

        def post_batch() -> None:
            if not shown:
                print("Nothing retrieved", end="")
                return
            # yaml = YAML(typ="safe")
            # yaml.Representer = RoundTripRepresenter
            # with bdb_path.open("wt") as fout:
            #     yaml.dump(BonnieDB, fout)

        await dispatch_fetcher(
            progress=Progress,
            duration=duration,
            taskmaker=make_task,
            result_handler=process_result,
            pre_batch=pre_batch,
            post_batch=post_batch,
            abort_event=AbortRequested,
            min_batch_size=min_batch_size,
            abort_low_rps=abort_low_rps,
        )


def main() -> None:  # noqa: D103
    global BonnieDetailsDB, Progress  # noqa: PLW0603
    yaml = YAML(typ="safe")
    yaml.Representer = RoundTripRepresenter

    bonnie_details_path = Path(Config.bonnie.dir) / Config.bonnie.db_details

    if bonnie_details_path.exists():
        print(f"Reading existing BonnieDB {bonnie_details_path} ...", end="", flush=True)
        with bonnie_details_path.open("rt") as fin:
            _bdb = yaml.load(fin)
        if isinstance(_bdb, dict):
            print(f" {len(_bdb)} records read.")
            # _bdb_k = list(_bdb.keys())
            # print(f"First key: <{type(_bdb_k[0])}>{_bdb_k[0]}")
            BonnieDetailsDB = _bdb
        else:
            print(" empty DB")
    Progress = BonnieProgress()
    print(f"Total to fetch: {Progress.total_to_fetch}", flush=True)
    time.sleep(3)

    try:
        make_backup(bonnie_details_path)
        AbortRequested.clear()
        asyncio.run(amain(-1, 100, 0))
    except asyncio.CancelledError:
        print("Something cancelled asyncio!")
    except KeyboardInterrupt:
        print("User Interrupted")
    finally:
        # pprint(BonnieDB)
        print(f"{len(BonnieDetailsDB)} regions in total now. Saving ...", end="", flush=True)
        with bonnie_details_path.open("wt") as fout:
            yaml.dump(BonnieDetailsDB, fout)
        print(f" saved to {bonnie_details_path}", flush=True)


if __name__ == "__main__":
    main()
