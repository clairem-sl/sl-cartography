# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import random
from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, NamedTuple

import httpx

from sl_maptools.utils import QuietablePrint

if TYPE_CHECKING:
    from sl_maptools import MapCoord


class FetcherConnectionError(ConnectionError):
    """Exception raised if Fetcher classes experienced a connection error."""

    def __init__(
        self,
        *args,
        internal_errors: list[Exception] | None = None,
        coord: MapCoord = None,
    ):
        """
        :param internal_errors: A list of internal errors
        """
        super().__init__(*args)
        self.internal_errors = internal_errors or []
        self.coord = coord

    def __str__(self):
        return f"MapConnectionError({self.coord.x}, {self.coord.y}): {self.internal_errors}"


class RawResult(NamedTuple):
    """Undecoded (bytes) result from HTTP"""

    coord: MapCoord
    result: bytes | None
    status_code: int = 0


class CookedResult(NamedTuple):
    """Unicode-decoded result from HTTP"""

    coord: MapCoord
    result: str | None
    status_code: int = 0


class Fetcher(metaclass=ABCMeta):
    """Perform name-fetching asynchronously"""

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
        acceptable_codes: set[int] | None = None,
    ) -> RawResult | None:
        """Get raw data for a coordinate asynchronously"""
        qprint = QuietablePrint(quiet, flush=True)
        qprint(".", end="")
        if acceptable_codes is None:
            acceptable_codes = {200, 403}
        url = self.URL_TEMPLATE.format(x=coord.x, y=coord.y)
        internal_errors = []
        multiplier = 0.25
        for _ in range(0, retries):
            multiplier *= 2.0
            await asyncio.sleep(random.random() * multiplier)  # noqa: S311
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
                return RawResult(coord, response.content, status_code)

            # Don't quiet this
            print(f"{status_code}?", end="", flush=True)
            internal_errors.append(f"Unexpected HTTP status code {response.status_code}")
            await asyncio.sleep(0.5)

        print(f"ERR({coord})", end="", flush=True)
        if raise_err:
            raise FetcherConnectionError(internal_errors=internal_errors, coord=coord)

        return None

    @abstractmethod
    async def async_get_cooked(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
        raise_err: bool = True,
        acceptable_codes: set[int] | None = None,
    ) -> CookedResult | None:
        """Get cooked (decoded) data for a coordinate asynchronously"""
        raise NotImplementedError()


class BoundedFetcher(Fetcher, metaclass=ABCMeta):
    """
    Wraps Fetcher in a way to limit in-flight fetches.

    It does this by implementing a semaphore of a certain size, and only launches an actual fetcher job when it can
    acquire a semaphore.

    This is to prevent throttling if we hit the maximum rps limit of the source server.
    """

    def __init__(
        self,
        sema_size: int,
        async_session: httpx.AsyncClient,
        *,
        retries: int = 3,
        timeout: int | None = None,
        cooked: bool = False,
        cancel_flag: asyncio.Event | None = None,
        suppress_cancelled_message: bool = True,
    ):
        """

        :param sema_size: Size of semaphore, which limits the number of in-flight requests
        :param async_session: The asynchronous httpx session to be used (connection pool, etc)
        :param retries: How many times to retry if request completes but we get an unexpected HTTP Status Code
        """
        super().__init__(a_session=async_session)
        self.sema = asyncio.Semaphore(sema_size)
        self.retries = retries
        self.timeout = timeout
        self.cooked = cooked
        self.cancel_flag = cancel_flag
        self.suppress_cancelled_message = suppress_cancelled_message

    async def async_fetch(self, coord: MapCoord) -> RawResult | CookedResult | None:
        """Perform async fetch, but won't actually start fetching if semaphore is depleted."""
        try:
            async with self.sema:
                if self.cancel_flag is not None and self.cancel_flag.is_set():
                    return None
                waitable = (
                    self.async_get_cooked(coord, quiet=True, retries=self.retries)
                    if self.cooked
                    else self.async_get_raw(coord, quiet=True, retries=self.retries)
                )
                return await asyncio.wait_for(waitable, self.timeout)
        except asyncio.CancelledError:
            if not self.suppress_cancelled_message:
                print(f"{coord} cancelled")
            raise
        except (TimeoutError, httpx.PoolTimeout):
            print(f"{coord} Timeout!")
            raise
