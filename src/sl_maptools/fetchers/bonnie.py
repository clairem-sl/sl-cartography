# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import json
from typing import NamedTuple, Optional

import httpx

from sl_maptools import MapCoord
from sl_maptools.fetchers import Fetcher


class CookedBonnieResult(NamedTuple):
    coord: MapCoord
    result: Optional[dict]
    status_code: int = 0


class BonnieFetcher(Fetcher):
    URL_TEMPLATE = "https://www.bonniebots.com/static-api/regions/{x}/{y}/index.json"

    async def async_get_data(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
        raise_err: bool = True,
    ) -> CookedBonnieResult:
        """ """
        blob: bytes
        status_code: int
        _, blob, status_code = await self.async_get_raw(coord, quiet, retries, raise_err)
        return CookedBonnieResult(coord, json.loads(blob.decode("utf-8")), status_code)


class BoundedBonnieFetcher(BonnieFetcher):
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
        retries: int = 6,
        timeout: int = 60,
        cancel_flag: Optional[asyncio.Event] = None,
    ):
        """

        :param sema_size: Size of semaphore, which limits the number of in-flight requests
        :param async_session: The asynchronous httpx session to be used (connection pool, etc)
        :param retries: How many times to retry if request completes but we get an unexpected HTTP Status Code
        """
        super().__init__(a_session=async_session)
        self.sema = asyncio.Semaphore(sema_size)
        self.retries = retries
        self.cancel_flag = cancel_flag
        self.timeout = timeout

    async def async_fetch(self, coord: MapCoord) -> Optional[CookedBonnieResult]:
        """Perform async fetch, but won't actually start fetching if semaphore is depleted."""
        try:
            async with self.sema:
                if self.cancel_flag is not None:
                    if self.cancel_flag.is_set():
                        return None
                return await asyncio.wait_for(self.async_get_data(coord, quiet=True, retries=self.retries), self.timeout)
        except asyncio.CancelledError:
            print(f"{coord} cancelled")
            raise
        except (asyncio.TimeoutError, httpx.PoolTimeout):
            print(f"{coord} Timeout!")
            raise
