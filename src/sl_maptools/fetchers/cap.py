# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar, Final, Protocol

import httpx

from sl_maptools.fetchers import BoundedFetcher, CookedResult, Fetcher, RawResult

if TYPE_CHECKING:
    from sl_maptools import MapCoord

RE_REGION_NAME: Final[re.Pattern] = re.compile(r"\s*var\s*region\s*=\s*(['\"])([^'\"]+)\1")


class MapProgressProtocol(Protocol):
    """Represents progress data"""

    regions: ClassVar[dict[MapCoord, Any]] = {}
    seen: ClassVar[set[MapCoord]] = set()
    last_fail_rows: ClassVar[set[int]] = set()


_RETRYABLE_EX: Final[tuple] = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError)


class NameFetcher(Fetcher):
    """Fetches region data from SL Cap server"""

    URL_TEMPLATE: Final[
        str
    ] = "https://cap.secondlife.com/cap/0/b713fe80-283b-4585-af4d-a3b7d9a32492?var=region&grid_x={x}&grid_y={y}"

    async def async_get_raw(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
        raise_err: bool = True,
        acceptable_codes: set[int] | None = None,
    ) -> RawResult:
        """Asynchronously return raw data from Cap server."""
        del acceptable_codes
        return await super().async_get_raw(coord, quiet, retries, raise_err, {200, 403})

    async def async_get_cooked(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
        raise_err: bool = True,
        acceptable_codes: set[int] | None = None,
    ) -> CookedResult:
        """Asynchronously get data from Cap server, and decodes it"""
        del acceptable_codes
        raw_result = await self.async_get_raw(coord, quiet, retries, raise_err)
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


class BoundedNameFetcher(NameFetcher, BoundedFetcher):
    """
    Wraps MapFetcher in a way to limit in-flight fetches.

    It does this by implementing a semaphore of a certain size, and only launches an actual fetcher job when it can
    acquire a semaphore.

    This is done to limit the concurrent hit against the SL Maps CDN, because empirical experience seems to indicate
    that if there are too many in-flight requests, we get throttled.
    """
