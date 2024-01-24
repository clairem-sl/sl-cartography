# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# This source file uses data & API provided by Tyche Shepherd & gridsurvey.com
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Generator, List, Set

import httpx
import msgpack

from gridsurvey import STATE_DIR, GridSurveyWeb, GridSurveyWebDatum
from sl_maptools.utils import make_backup

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


RE_PAGEOF = re.compile(r"Showing page \d+ of (\d+) pages")
GS_DATA = STATE_DIR / Path("gridsurvey_webdata.msgp")
PAGE_CACHE = STATE_DIR / Path("gridsurvey_pagecache.pickle")


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
