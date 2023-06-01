# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import random
import re
from typing import Any, Dict, Final, Optional, Protocol, Set

import httpx

from sl_maptools import MapCoord
from sl_maptools.fetchers import CookedResult, Fetcher, FetcherConnectionError, RawResult
from sl_maptools.utils import QuietablePrint

RE_REGION_NAME: Final[re.Pattern] = re.compile(
    r"\s*var\s*region\s*=\s*(['\"])([^'\"]+)\1"
)


class MapProgressProtocol(Protocol):
    regions: Dict[MapCoord, Any] = {}
    seen: Set[MapCoord] = set()
    last_fail_rows: Set[int] = set()


_RETRYABLE_EX: Final[tuple] = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError)


class NameFetcher(Fetcher):
    URL_TEMPLATE: Final[str] = (
        "https://cap.secondlife.com/cap/0/b713fe80-283b-4585-af4d-a3b7d9a32492?"
        "var=region&grid_x={x}&grid_y={y}"
    )

    async def async_get_name_raw(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
        raise_err: bool = True,
    ) -> RawResult:
        """ """
        return await self.async_get_raw(coord, quiet, retries, raise_err, {200, 403})

    async def async_get_name(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
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

    def __init__(
        self,
        sema_size: int,
        async_session: httpx.AsyncClient,
        retries: int = 3,
        cooked: bool = False,
        cancel_flag: asyncio.Event = None,
    ):
        """

        :param sema_size: Size of semaphore, which limits the number of in-flight requests
        :param async_session: The asynchronous httpx session to be used (connection pool, etc)
        :param retries: How many times to retry if request completes but we get an unexpected HTTP Status Code
        """
        super().__init__(a_session=async_session)
        self.sema = asyncio.Semaphore(sema_size)
        self.retries = retries
        self.cooked = cooked
        self.cancel_flag = cancel_flag

    async def async_fetch(self, coord: MapCoord) -> Optional[RawResult | CookedResult]:
        """Perform async fetch, but won't actually start fetching if semaphore is depleted."""
        try:
            async with self.sema:
                if self.cancel_flag is not None:
                    if self.cancel_flag.is_set():
                        return None
                if self.cooked:
                    return await self.async_get_name(
                        coord, quiet=True, retries=self.retries
                    )
                else:
                    return await self.async_get_name_raw(
                        coord, quiet=True, retries=self.retries
                    )
        except asyncio.CancelledError:
            print(f"{coord} cancelled")
            raise
