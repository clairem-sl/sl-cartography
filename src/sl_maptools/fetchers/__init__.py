# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import abc
import asyncio
import random
from typing import NamedTuple

import httpx

from sl_maptools import MapCoord
from sl_maptools.utils import QuietablePrint


class FetcherConnectionError(ConnectionError):
    def __init__(self, *args, internal_errors: list[Exception] = None, coord: MapCoord = None):
        super(FetcherConnectionError, self).__init__(*args)
        self.internal_errors = internal_errors or []
        self.coord = coord

    def __str__(self):
        return f"MapConnectionError({self.coord.x}, {self.coord.y}): {self.internal_errors}"


class RawResult(NamedTuple):
    coord: MapCoord
    result: bytes | None
    status_code: int = 0


class CookedResult(NamedTuple):
    coord: MapCoord
    result: str | None
    status_code: int = 0


class Fetcher(metaclass=abc.ABCMeta):
    URL_TEMPLATE: str = ""
    RETRYABLE_EX: tuple[Exception, ...] = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError)

    def __init__(self, a_session: httpx.AsyncClient):
        """
        Creates a Map Tile Getter with logic to retrieve map tiles

        :param a_session: An Async client session
        """
        self.a_session: httpx.AsyncClient = a_session

    async def async_get_raw(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
        raise_err: bool = True,
        acceptable_codes: set[int] = None,
    ) -> RawResult:
        """ """
        qprint = QuietablePrint(quiet, flush=True)
        qprint(".", end="")
        if acceptable_codes is None:
            acceptable_codes = {200}
        url = self.URL_TEMPLATE.format(x=coord.x, y=coord.y)
        internal_errors = []
        multiplier = 0.25
        for _ in range(0, retries):
            multiplier *= 2.0
            await asyncio.sleep(random.random() * multiplier)
            try:
                response = await self.a_session.get(url)
            except self.RETRYABLE_EX as e1:
                # Not quietable
                print(">", end="", flush=True)
                internal_errors.append(e1)
                continue
            except Exception as e:
                raise FetcherConnectionError(internal_errors=[e], coord=coord) from e

            status_code = response.status_code

            if status_code in acceptable_codes:
                qprint("+", end="")
                return RawResult(coord, response.content, status_code)

            # Don't quiet this
            print(f"{status_code}?", end="", flush=True)
            internal_errors.append(f"Unexpected HTTP status code {response.status_code}")
            await asyncio.sleep(0.5)

        print(f"ERR({coord})", end="", flush=True)
        if raise_err:
            raise FetcherConnectionError(internal_errors=internal_errors, coord=coord)
