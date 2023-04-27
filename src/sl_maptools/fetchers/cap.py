# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import random
import re
from typing import Any, Dict, Final, NamedTuple, Optional, Protocol, Set

import httpx

from sl_maptools import MapCoord
from sl_maptools.fetchers import FetcherConnectionError, RawResult, CookedResult
from sl_maptools.utils import QuietablePrint


RE_REGION_NAME: Final[re.Pattern] = re.compile(r"\s*var\s*region\s*=\s*(['\"])([^'\"]+)\1")


class MapProgressProtocol(Protocol):
    regions: Dict[MapCoord, Any] = {}
    seen: Set[MapCoord] = set()
    last_fail_rows: Set[int] = set()


_RETRYABLE_EX: Final[tuple] = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError)


class NameFetcher(object):
    URL_TEMPLATE: Final[str] = (
        "https://cap.secondlife.com/cap/0/b713fe80-283b-4585-af4d-a3b7d9a32492?"
        "var=region&grid_x={x}&grid_y={y}"
    )

    def __init__(self, a_session: httpx.AsyncClient):
        """
        Creates a Map Tile Getter with logic to retrieve map tiles

        :param a_session: An Async client session
        """
        self.a_session: httpx.AsyncClient = a_session

    async def async_get_name_raw(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 2,
        raise_err: bool = True,
    ) -> RawResult:
        """
        """
        qprint = QuietablePrint(quiet)
        qprint(".", end="", flush=True)
        url = self.URL_TEMPLATE.format(x=coord.x, y=coord.y)
        internal_errors = []
        multiplier = 0.25
        for _ in range(0, retries):
            multiplier *= 2.0
            await asyncio.sleep(random.random() * multiplier)

            for _ in range(0, 8):
                mul2 = 0.5
                try:
                    response = await self.a_session.get(url)
                    break
                except _RETRYABLE_EX as e1:
                    # Not quietable
                    print(">", end="", flush=True)
                    internal_errors.append(e1)
                    await asyncio.sleep(random.random() * mul2)
                    mul2 *= 2.0
                    continue
                except Exception as e:
                    raise FetcherConnectionError(internal_errors=[e], coord=coord)
            else:
                break

            status_code = response.status_code

            if status_code == 403:
                # "403 Forbidden" means the tile is a void
                qprint(status_code, end=" ", flush=True)
                # return MapTile(coord, None)
                return RawResult(coord, str(status_code).encode("utf-8"), status_code)

            if status_code == 200:
                qprint("+", end="", flush=True)
                # with io.BytesIO(response.content) as bio:
                #     grabbed = Image.open(bio)
                #     # Need to call .load() because .open() is lazy
                #     grabbed.load()
                # return MapTile(coord, grabbed)
                return RawResult(coord, response.content, status_code)

            # Don't quiet this
            print(f"{status_code}?", end="", flush=True)
            internal_errors.append(
                f"Unexpected HTTP status code {response.status_code}"
            )
            await asyncio.sleep(0.5)
        print(f"ERR({coord})", end="", flush=True)
        if raise_err:
            raise FetcherConnectionError(internal_errors=internal_errors, coord=coord)

    async def async_get_name(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 2,
        raise_err: bool = True,
    ) -> CookedResult:
        raw_result = await self.async_get_name_raw(coord, quiet, retries, raise_err)
        if raw_result.result is None:
            return CookedResult(coord, None)
        rsltb: bytes = raw_result.result
        assert isinstance(rsltb, bytes)
        rslt: str = rsltb.decode("utf-8")
        if rslt.isdigit():
            return CookedResult(coord, rslt, raw_result.status_code)
        matches = RE_REGION_NAME.match(rslt)
        if not matches:  # Void
            return CookedResult(coord, None, raw_result.status_code)
        return CookedResult(coord, matches.group(2), raw_result.status_code)


class BoundedNameFetcher(NameFetcher):
    """
    Wraps MapFetcher in a way to limit in-flight fetches.

    It does this by implementing a semaphore of a certain size, and only launches an actual fetcher job when it can
    acquire a semaphore.

    This is done to limit the concurrent hit against the SL Maps CDN, because empirical experience seems to indicate
    that if there are too many in-flight requests, we get throttled.
    """

    def __init__(self, sema_size: int, async_session: httpx.AsyncClient, retries: int = 3, cooked: bool = False):
        """

        :param sema_size: Size of semaphore, which limits the number of in-flight requests
        :param async_session: The asynchronous httpx session to be used (connection pool, etc)
        :param retries: How many times to retry if request completes but we get an unexpected HTTP Status Code
        """
        super().__init__(a_session=async_session)
        self.sema = asyncio.Semaphore(sema_size)
        self.retries = retries
        self.cooked = cooked

    async def async_fetch(self, coord: MapCoord) -> Optional[RawResult | CookedResult]:
        """Perform async fetch, but won't actually start fetching if semaphore is depleted."""
        async with self.sema:
            try:
                if self.cooked:
                    return await self.async_get_name(coord, quiet=True, retries=self.retries)
                else:
                    return await self.async_get_name_raw(coord, quiet=True, retries=self.retries)
            except asyncio.CancelledError:
                print(f"{coord} cancelled")
                return None
