# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import json
from typing import TYPE_CHECKING, NamedTuple, Optional

from sl_maptools.fetchers import BoundedFetcher, Fetcher

if TYPE_CHECKING:
    from sl_maptools import MapCoord


class CookedBonnieResult(NamedTuple):
    """Represents BonnieBots region retrieval result, decoded from JSON"""

    coord: MapCoord
    result: Optional[dict]
    status_code: int = 0


class BonnieFetcher(Fetcher):
    """Fetch region data from BonnieBots"""

    URL_TEMPLATE = "https://www.bonniebots.com/static-api/regions/{x}/{y}/index.json"

    async def async_get_cooked(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 6,
        raise_err: bool = True,
        acceptable_codes: Optional[set[int]] = None,
    ) -> CookedBonnieResult:
        """Asynchronously retrieves and decodes region data from BonnieBots"""
        del acceptable_codes
        blob: bytes
        status_code: int
        _, blob, status_code = await self.async_get_raw(coord, quiet, retries, raise_err)
        return CookedBonnieResult(coord, json.loads(blob.decode("utf-8")), status_code)


class BoundedBonnieFetcher(BonnieFetcher, BoundedFetcher):
    """
    Wraps BonnieFetcher in a way to limit in-flight fetches.

    It does this by implementing a semaphore of a certain size, and only launches an actual fetcher job when it can
    acquire a semaphore.

    This is done to limit the concurrent hit against the SL Maps CDN, because empirical experience seems to indicate
    that if there are too many in-flight requests, we get throttled.
    """

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        """See documentation for BoundedFetcher.__init__"""
        kwargs["cooked"] = True
        super().__init__(*args, **kwargs)
