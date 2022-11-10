# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# This source file uses data & API provided by Tyche Shepherd & gridsurvey.com

import datetime
from itertools import islice
import uuid

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Union, Tuple

import httpx
import msgpack

from sl_maptools import MapTile, MapCoord

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
        kvp = {
            k: v for k, v in zip(islice(elems, 0, None, 2), islice(elems, 1, None, 2))
        }
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
        self.cache = {
            MapCoord(*coord): GridSurveyDatum.from_str(datum_str)
            for coord, datum_str in cac
        }

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

    async def validate_tile(self, tile: MapTile) -> bool:
        _, gs_datum = await self.fetch_gs_data(tile.coord)
        if tile.is_void and gs_datum is GridSurvey_NotRegion:
            return True
        if not tile.is_void and gs_datum:
            return True
        return False

    async def coord_is_region(self, coord: MapCoord) -> bool:
        gs_datum = await self.fetch_gs_data(coord)
        return gs_datum is not GridSurvey_NotRegion
