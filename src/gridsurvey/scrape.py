# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
import time
from pathlib import Path
from typing import Generator, Set, List

import httpx
import msgpack
from bs4 import BeautifulSoup

from gridsurvey import GridSurveyWebDatum, GridSurveyWeb
from sl_maptools.utils import make_backup

RE_PAGEOF = re.compile(r"Showing page \d+ of (\d+) pages")
GS_DATA = Path("gridsurvey_webdata.msgp")
PAGE_CACHE = Path("gridsurvey_pagecache.pickle")


def parse_soup(soup: BeautifulSoup) -> Generator[GridSurveyWebDatum, None, None]:
    # print("\u25ad", end="", flush=True)
    reglist = soup.find(id="regionlist")
    tbody = reglist.find("tbody")
    for row in tbody.find_all("tr"):
        tds = row.find_all("td")
        rowdata = [tds[0].text, tds[1].text]
        rowdata.extend(td.find("img")["alt"] for td in tds[2:5])
        yield GridSurveyWebDatum.from_row_contents(*rowdata)
    # print("\u25ac", end="", flush=True)


# def get_soup(
#     client: httpx.Client,
#     url: str,
#     cache: Path = None,
#     force_refresh: bool = False,
#     limit_age: int = 7,
#     retries: int = 3,
# ) -> Tuple[BeautifulSoup, bool]:
#     cached_pages: Dict[str, Union[str, Tuple[datetime.date, str]]]
#     if cache is not None and cache.exists() and cache.stat().st_size > 0:
#         with cache.open("rb") as fin:
#             cached_pages = pickle.load(fin)
#     else:
#         cached_pages = {}
#     _today = datetime.date.today()
#     for k, v in cached_pages.items():
#         if isinstance(v, str):
#             cached_pages[k] = _today, v
#     from_cache = False
#     cpage: Union[None, Tuple[datetime.date, str]] = cached_pages.get(url)
#     page: str
#     if (
#         force_refresh
#         or cpage is None
#         or (_today - cpage[0]) > datetime.timedelta(days=limit_age)
#     ):
#         eh = None
#         dly = 0.5
#         for retry in range(retries):
#             try:
#                 resp = client.get(url)
#                 if resp.status_code == 200:
#                     break
#             except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.Timeout) as eh:
#                 pass
#             print("!", end="", flush=True)
#             time.sleep(dly)
#             dly *= (1 + random.random())
#         else:
#             if eh:
#                 raise eh
#             raise ConnectionError("Server seems to be out")
#         print("\u25bc", end="", flush=True)
#         page = resp.text
#         if cache is not None:
#             cached_pages[url] = (_today, page)
#             cache_suff = cache.suffix
#             cache_temp = cache.with_suffix(".temp" + cache_suff)
#             with cache_temp.open("wb") as fout:
#                 pickle.dump(cached_pages, fout, protocol=pickle.HIGHEST_PROTOCOL)
#             cache_temp.replace(cache)
#     else:
#         print("\u25b3", end="", flush=True)
#         from_cache = True
#         page = cpage[1]
#     soup = BeautifulSoup(page, "html.parser")
#     return soup, from_cache


def save(regions: Set[GridSurveyWebDatum]):
    suff = GS_DATA.suffix
    temp = GS_DATA.with_suffix(".temp" + suff)
    with temp.open("wb") as fout:
        msgpack.dump([d.encode() for d in regions], fout)
    temp.replace(GS_DATA)


def main(timeout: float = 90.0, interpage_delay: int = 5):
    make_backup(PAGE_CACHE)
    page = 1
    regions: Set[GridSurveyWebDatum] = set()
    doubles: List[GridSurveyWebDatum] = []
    try:
        with httpx.Client(timeout=timeout, http2=True) as client:
            gridsurvey = GridSurveyWeb(client, PAGE_CACHE)

            print("Initializing", flush=True)
            gridsurvey.prime()

            print("Grab first page & parse ... ", end="", flush=True)
            try:
                soup, _ = gridsurvey.get_page_soup(1)
            except Exception as egs:
                print(f"get_page_soup exception {type(egs)}: {egs}")
                raise
            pageof = soup.find("caption")
            matches = RE_PAGEOF.search(pageof.text)
            last_page = int(matches[1])
            regions.update(data for data in parse_soup(soup))
            print(f" {last_page} total pages.")

            for page in range(2, last_page + 1):
                save(regions)

                print(f"Grab page {page}/{last_page} ...", end="", flush=True)
                try:
                    soup, from_cache = gridsurvey.get_page_soup(page)
                except Exception as egs:
                    print(f"get_page_soup exception {type(egs)}: {egs}")
                    raise

                print(" parsing ...", end="", flush=True)
                new_regions = set(data for data in parse_soup(soup))
                if intersect := regions & new_regions:
                    print(" doubles!", end="", flush=True)
                    doubles.extend(intersect)
                regions.update(new_regions)

                print(" done", end="", flush=True)
                if not from_cache:
                    for _ in range(interpage_delay):
                        print(".", end="", flush=True)
                        time.sleep(1.0)
                print()
        print("ALL DONE!")
    except KeyboardInterrupt:
        print("\nUser aborted!")
    except Exception as e:
        print(f"Exception {type(e)}: {e} (on page {page})")
        raise
    finally:
        if doubles:
            print("Found doubles for the following regions:")
            for d in doubles:
                print(d)
        save(regions)


if __name__ == "__main__":
    main()
