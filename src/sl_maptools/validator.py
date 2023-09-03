# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import datetime
import random
import re
import urllib.parse
import uuid
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Dict, Final, Tuple, Union

import httpx
import msgpack
from ruamel import yaml as ryaml

from sl_maptools import CoordType, MapCoord, MapRegion, RE_MAPFILE

# This source file uses data & API provided by Tyche Shepherd & gridsurvey.com

"""
status online x 1000 y 1000 access moderate estate Mainland firstseen 2008-03-09 lastseen 2022-11-06 \
objects_uuid 66a40961-1669-55fc-11f6-73d9eb1e1858 terrain_uuid b52b420a-94f6-eff7-ce6e-09cd07eb9c53 \
incidents 0 updated 2022-11-06 region_uuid 4126bd1e-964a-590a-d55f-e160475fde4b name Da+Boom
"""


@dataclass(frozen=True)
class GridSurveyDatum(object):
    status: str
    x: int
    y: int
    access: str
    estate: str
    firstseen: datetime.date
    lastseen: datetime.date
    objects_uuid: uuid.UUID
    terrain_uuid: uuid.UUID
    incidents: int
    updated: datetime.date
    region_uuid: uuid.UUID
    name: str

    @classmethod
    def from_str(cls, string):
        elems = string.split()
        kvp = {k: v for k, v in zip(islice(elems, 0, None, 2), islice(elems, 1, None, 2))}
        kvp["x"] = int(kvp["x"])
        kvp["y"] = int(kvp["y"])
        for dk in ("firstseen", "lastseen", "updated"):
            kvp[dk] = datetime.datetime.strptime(kvp[dk], "%Y-%m-%d").date()
        for uk in ("objects_uuid", "terrain_uuid", "region_uuid"):
            kvp[uk] = uuid.UUID(kvp[uk])
        return cls(**kvp)

    def encode(self) -> str:
        return (
            f"status {self.status} x {self.x} y {self.y} access {self.access} "
            f"estate {self.estate} firstseen {self.firstseen.strftime('%Y-%m-%d')} "
            f"lastseen {self.lastseen.strftime('%Y-%m-%d')} "
            f"objects_uuid {self.objects_uuid} terrain_uuid {self.terrain_uuid} "
            f"incidents {self.incidents} updated {self.updated.strftime('%Y-%m-%d')} "
            f"region_uuid {self.region_uuid} "
            f"name {urllib.parse.quote_plus(self.name)}"
        )


class GridSurveyError(object):
    pass


GridSurvey_NotRegion = GridSurveyError()


class MapValidatorGridSurvey(object):
    GRIDSURVEY_API = "http://api.gridsurvey.com/simquery.php?xy={x},{y}"

    def __init__(self, a_session: httpx.AsyncClient, cache_file: Path = None):
        self.session = a_session
        self.cache_file = cache_file
        if cache_file is None or not cache_file.exists():
            self.cache: Dict[MapCoord, GridSurveyDatum] = {}
            return
        with cache_file.open("rb") as fin:
            cac = msgpack.unpack(fin)
        self.cache = {MapCoord(*coord): GridSurveyDatum.from_str(datum_str) for coord, datum_str in cac}

    async def fetch_gs_data(
        self, coord: MapCoord, use_cache: bool = True
    ) -> Tuple[MapCoord, Union[GridSurveyDatum, GridSurveyError]]:
        if use_cache and (datum := self.cache.get(coord)):
            return coord, datum
        url = self.GRIDSURVEY_API.format(x=coord.x, y=coord.y)
        response = await self.session.get(url)
        status_code = response.status_code

        if status_code != 200:
            raise RuntimeError(f"Got error {status_code} for {coord}")

        text = response.text
        text_cfold = text.strip().casefold()
        if text_cfold.startswith("error"):
            if "013_no_active_region_found_at_that_location" in text_cfold:
                return coord, GridSurvey_NotRegion
            raise RuntimeError(f"Unknown error: {text}")

        datum = GridSurveyDatum.from_str(response.text)
        self.cache[coord] = datum
        if self.cache_file:
            with self.cache_file.open("wb") as fout:
                msgpack.pack(fout, [(tuple(coord), d.encode()) for coord, d in self.cache.items()])
        return coord, datum

    async def validate_tile(self, tile: MapRegion) -> bool:
        _, gs_datum = await self.fetch_gs_data(tile.coord)
        if tile.is_void and gs_datum is GridSurvey_NotRegion:
            return True
        if not tile.is_void and gs_datum:
            return True
        return False

    async def coord_is_region(self, coord: MapCoord) -> bool:
        gs_datum = await self.fetch_gs_data(coord)
        return gs_datum is not GridSurvey_NotRegion


"""var slRegionName = {'error' : true };"""
RE_ERROR = re.compile(r"=\s*\{\s*'error'\s+:\s+true\s*}")
"""var slRegionName='Da Boom';"""


class MapValidator(object):
    UUID = "b713fe80-283b-4585-af4d-a3b7d9a32492"
    URL = "https://cap.secondlife.com/cap/0/{uuid}?var=slRegionName&grid_x={x}&grid_y={y}"

    def __init__(self, a_session: httpx.AsyncClient, retries: int = 5):
        self.a_session = a_session
        self.retries = retries

    async def is_region(self, coord: MapCoord) -> Tuple[MapCoord, bool]:
        delay = 0.5
        url = self.URL.format(uuid=self.UUID, x=coord.x, y=coord.y)
        for _ in range(self.retries):
            await asyncio.sleep(random.random() * 2.0)
            # noinspection PyBroadException
            try:
                resp = await self.a_session.get(url)
            except Exception:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                if resp.status_code == 200:
                    return coord, not RE_ERROR.search(resp.text)
        raise ConnectionError()

    async def validate_tile(self, tile: MapRegion) -> Tuple[MapRegion, bool]:
        _, is_reg = await self.is_region(tile.coord)
        is_void: bool = tile.is_void
        # Both are bool so we can use bitwise-xor
        return tile, is_reg ^ is_void


BONNIE_REGDB_URL: Final[str] = "https://www.bonniebots.com/static-api/regions/index.json"


def get_bonnie_coords(bonniedb: None | Path, fetchbonnie: bool) -> set[CoordType]:
    """
    Returns a set of valid coordinates from BonnieBots DB.

    :param bonniedb: Path to BonnieBots DB file, or None
    :param fetchbonnie: If True, then fetch from BonnieBots API
    """
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
    return {(int(record["region_x"]), int(record["region_y"])) for record in bdb_data_raw["regions"]}


def inventorize_maps_latest(mapdir: Path | str) -> dict[CoordType, Path]:
    """Returns a dict of maptile paths, with the coord as key"""
    mapdir = Path(mapdir)
    rslt: dict[CoordType, Path] = {}
    for fp in sorted(mapdir.glob("*.jp*"), reverse=True):
        if (m := RE_MAPFILE.match(fp.name)) is None:
            continue
        coord = int(m.group("x")), int(m.group("y"))
        if coord not in rslt:
            rslt[coord] = fp
    return rslt


def inventorize_maps_all(mapdir: Path) -> dict[CoordType, list[Path]]:
    """
    Returns a dict (by coordinate) of maptile files in mapdir, sorted ascending by filename.
    (So if filename has timestamp, the latest will be the last)

    :param mapdir: Directory containing the maptile files
    """
    rslt: dict[CoordType, list[Path]] = {}
    for fp in sorted(mapdir.glob("*.jp*")):
        if (m := RE_MAPFILE.match(fp.name)) is None:
            continue
        coord = int(m.group("x")), int(m.group("y"))
        rslt.setdefault(coord, []).append(fp)
    return rslt
