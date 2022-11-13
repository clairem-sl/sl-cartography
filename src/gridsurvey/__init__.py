# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# This source file uses data & API provided by Tyche Shepherd & gridsurvey.com

import datetime
import pickle
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple, Dict, Union

import appdirs
import httpx
from bs4 import BeautifulSoup

from sl_maptools import MapCoord

RE_COORD = re.compile(r"\((\d+),(\d+)\)")
STATE_DIR = Path(appdirs.site_data_dir("sl-cartography"))


@dataclass(eq=True, frozen=True)
class GridSurveyWebDatum(object):
    name: str
    coord: MapCoord
    rating: str
    regtype: str = field(compare=False)
    active: bool = field(compare=False)
    last_update: datetime.date = field(
        default_factory=datetime.date.today, compare=False
    )

    @classmethod
    def from_row_contents(
        cls,
        name: str,
        coord: str,
        rating: str,
        regtype: str,
        active: str,
    ):
        matches = RE_COORD.match(coord)
        _coord = MapCoord(matches[1], matches[2])
        return cls(
            name,
            _coord,
            rating[0],
            regtype,
            (active[0] == "Y"),
        )

    def encode(self):
        d = self.__dict__.copy()
        d["coord"] = tuple(self.coord)
        d["last_update"] = self.last_update.isoformat()
        return d

    @classmethod
    def decode(cls, obj):
        obj["coord"] = MapCoord(*(obj["coord"]))
        obj["last_update"] = datetime.date.fromisoformat(obj["last_update"])
        return cls(**obj)


class GridSurveyWeb(object):
    URL_TEMPLATE = "http://www.gridsurvey.com/index.php?page={page}"
    _ACCEPTABLE_EX = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout)

    def __init__(self, client: httpx.Client, cache: Path = None):
        self.client = client
        self.cache = cache
        self._cached_pages: Dict[str, Union[str, Tuple[datetime.date, str]]] = {}

    def read_cache(self):
        cache = self.cache
        if cache is not None and cache.exists() and cache.stat().st_size > 0:
            with cache.open("rb") as fin:
                self._cached_pages = pickle.load(fin)

    def save_cache(self):
        if self.cache is None:
            return
        cache = self.cache
        cache_suff = cache.suffix
        cache_temp = cache.with_suffix(".temp" + cache_suff)
        with cache_temp.open("wb") as fout:
            pickle.dump(self._cached_pages, fout, protocol=pickle.HIGHEST_PROTOCOL)
        cache_temp.replace(cache)

    def prime(self, active_only: bool = True, read_cache: bool = True):
        self.client.get("http://www.gridsurvey.com/index.php?page=1")
        if not active_only:
            return
        payload = {
            "region": "",
            "active_only": "on",
        }
        self.client.post(
            "http://www.gridsurvey.com/action.toggleactive.php", data=payload
        )
        if read_cache:
            self.read_cache()

    def get_page_soup(
        self,
        page: int,
        force_refresh: bool = False,
        limit_age: int = 7,
        retries: int = 3,
    ) -> Tuple[BeautifulSoup, bool]:
        url = self.URL_TEMPLATE.format(page=page)
        client = self.client
        _today = datetime.date.today()
        cached_pages = self._cached_pages

        for k, v in cached_pages.items():
            if isinstance(v, str):
                cached_pages[k] = _today, v

        cpage: Union[None, Tuple[datetime.date, str]] = cached_pages.get(url)

        can_use_cache = not (
            force_refresh
            or cpage is None
            or (_today - cpage[0]) > datetime.timedelta(days=limit_age)
        )

        if can_use_cache:
            print("\u25b3", end="", flush=True)
            return BeautifulSoup(cpage[1], "html.parser"), True

        eh = None
        dly = 0.5
        st_t = time.monotonic()
        for retry in range(retries):
            try:
                resp = client.get(url)
                if resp.status_code == 200:
                    break
            except self._ACCEPTABLE_EX as eh:
                pass
            print("!", end="", flush=True)
            time.sleep(dly)
            dly *= 1 + random.random()
        else:
            if eh:
                raise eh
            raise ConnectionError("Server seems to be out")
        el_t = time.monotonic() - st_t
        print(f"\u25bc{el_t:,.2f}s", end="", flush=True)
        page = resp.text
        self._cached_pages[url] = page
        self.save_cache()
        return BeautifulSoup(page, "html.parser"), False


"""
Session open website
    http://www.gridsurvey.com/index.php?page=1
Session send POST:
    http://www.gridsurvey.com/action.toggleactive.php
        Payload:
            region: ''
            active_only: 'on'
Session open website no cache:
    http://www.gridsurvey.com/index.php?page=1
        Grab total number of pages
Parse Page
Loop from page 2 to <last page>
"""
