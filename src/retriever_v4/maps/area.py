# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import argparse
import asyncio
import re
from datetime import datetime
from fnmatch import fnmatch
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

import httpx

from sl_maptools import RE_SLGI_NOTATION, AreaDescriptor, MapCoord
from sl_maptools.config import DefaultConfig as Config
from sl_maptools.fetchers.map import MapFetcher
from sl_maptools.knowns import KNOWN_AREAS

if TYPE_CHECKING:
    from sl_maptools.fetchers import RawResult


RE_BOXCOORDS = re.compile(r"(?P<x1>\d+),(?P<y1>\d+)[,-](?P<x2>\d+),(?P<y2>\d+)")


class Options(NamedTuple):
    """Represents options extracted from the CLI"""

    area: list[str]


def get_options() -> Options:
    """Get option from the CLI"""
    parser = argparse.ArgumentParser()

    parser.add_argument("area", type=str, nargs="+")

    _opts = parser.parse_args()

    return cast(Options, _opts)


async def aretrieve(wants: dict[str, list[tuple[int, int, int, int]]]) -> None:
    """Performs asynchronous retrieval of wanted areas"""
    seen: set[tuple[int, int]] = set()
    async with httpx.AsyncClient(http2=True) as aclient:
        fetcher = MapFetcher(a_session=aclient)
        for name, lista in wants.items():
            print(f"Retrieving {name}:")
            for x1, y1, x2, y2 in lista:
                tasks = [
                    asyncio.create_task(fetcher.async_get_raw(MapCoord(*xy), quiet=True))
                    for xy in product(range(x1, x2 + 1), range(y1, y2 + 1))
                    if xy not in seen
                ]
            totlen = len(str(tot := len(tasks)))
            targdir = Path(Config.maps.dir)
            reg_c = 0
            for c, fut in enumerate(asyncio.as_completed(tasks), start=1):
                mr: RawResult = await fut
                if mr.result is None:
                    continue
                x, y = mr.coord
                ts = datetime.strftime(datetime.now().astimezone(), "%y%m%d-%H%M")
                targ = targdir / f"{x}-{y}_{ts}.jpg"
                with targ.open("wb") as fout:
                    fout.write(mr.result)
                print(f"  ({c:{totlen}}/{tot}) {targ}")
                reg_c += 1
                seen.add((x, y))
            print(f"  = {reg_c} actual regions")


def main(opts: Options) -> None:  # noqa: D103
    known_folded: dict[str, AreaDescriptor] = {k.casefold(): desc for k, desc in KNOWN_AREAS.items()}

    wants: dict[str, list[tuple[int, int, int, int]]] = {}

    for want in opts.area:
        print(f"Want: {want}")
        if m := RE_BOXCOORDS.match(want):
            x1, y1, x2, y2 = m.groups()
            wants[want] = [x1, y1, x2, y2]
            continue
        if m := RE_SLGI_NOTATION.match(want):
            x1, y1, x2, y2 = m.groups()
            wants[want] = [x1, y1, x2, y2]
            continue
        if (area_desc := known_folded.get(want.casefold())) is not None:
            wants[want] = list(area_desc.includes)
            continue
        for k, area_desc in known_folded.items():
            if fnmatch(k, want.casefold()):
                wants[want] = list(area_desc.includes)
    print(f"Parsed {len(wants)} areas")

    if wants:
        asyncio.run(aretrieve(wants))


if __name__ == "__main__":
    main(get_options())
