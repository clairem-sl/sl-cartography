# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import asyncio
import io
import random
import time
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Protocol, Set, Tuple, Union

import httpx
from PIL import Image

from sl_maptools import MapCoord, MapRegion
from sl_maptools.knowns import VERIFIED_VOIDS
from sl_maptools.utils import QuietablePrint


RawRegion = Tuple[MapCoord, bytes | None]


_REGION_SIZE = 256


class MapConnectionError(ConnectionError):
    def __init__(
        self, *args, internal_errors: List[Exception] = None, coord: MapCoord = None
    ):
        super(MapConnectionError, self).__init__(*args)
        self.internal_errors = internal_errors or []
        self.coord = coord

    def __str__(self):
        return f"MapConnectionError({self.coord.x}, {self.coord.y}): {self.internal_errors}"


class MapProgressProtocol(Protocol):
    regions: Dict[MapCoord, Any] = {}
    seen: Set[MapCoord] = set()
    last_fail_rows: Set[int] = set()


_RETRYABLE_EX = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError)


class MapFetcher(object):
    URL_TEMPLATE = (
        "https://secondlife-maps-cdn.akamaized.net/map-1-{map_x}-{map_y}-objects.jpg"
    )

    def __init__(
        self,
        skip_tiles: Set[MapCoord] = None,
        a_session: httpx.AsyncClient = None,
    ):
        """
        Creates a Map Tile Getter with logic to retrieve map tiles

        :param skip_tiles: A Set of coordinates to skip from being fetched
        :param a_session: An Async client session
        """
        self.skip_tiles: Set[MapCoord] = set() if skip_tiles is None else skip_tiles
        self.a_session: httpx.AsyncClient = a_session

    async def async_get_region_raw(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 2,
        raise_err: bool = True,
    ) -> RawRegion:
        """
        Asynchronously fetch a map tile from a given coordinate

        :param coord: Map's coordinates
        :param quiet: If False (default), will emit progress indicator
        :param retries: How many times to retry if fetching attempt results in error (default = 3)
        :param raise_err: If True (default), will (re-)raise error
        :return: An instance of MapTile fetched from (X, Y)
        """
        qprint = QuietablePrint(quiet)
        qprint(".", end="", flush=True)
        if coord in self.skip_tiles or coord in VERIFIED_VOIDS:
            # return MapTile(coord, None)
            return coord, None
        url = self.URL_TEMPLATE.format(map_x=coord.x, map_y=coord.y)
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
                    raise MapConnectionError(internal_errors=[e], coord=coord)
            else:
                break

            status_code = response.status_code

            if status_code == 403:
                # "403 Forbidden" means the tile is a void
                qprint("-", end="", flush=True)
                # return MapTile(coord, None)
                return coord, None

            if status_code == 200:
                qprint("+", end="", flush=True)
                # with io.BytesIO(response.content) as bio:
                #     grabbed = Image.open(bio)
                #     # Need to call .load() because .open() is lazy
                #     grabbed.load()
                # return MapTile(coord, grabbed)
                return coord, response.content

            # Don't quiet this
            print(f"{status_code}?", end="", flush=True)
            internal_errors.append(
                f"Unexpected HTTP status code {response.status_code}"
            )
            await asyncio.sleep(0.5)
        print(f"ERR({coord})", end="", flush=True)
        if raise_err:
            raise MapConnectionError(internal_errors=internal_errors, coord=coord)

    async def async_get_region(
        self,
        coord: MapCoord,
        quiet: bool = False,
        retries: int = 2,
        raise_err: bool = True,
    ) -> MapRegion:
        coord, raw = await self.async_get_region_raw(coord, quiet, retries, raise_err)
        if raw is None:
            return MapRegion(coord, None)

        with io.BytesIO(raw) as bio:
            grabbed = Image.open(bio)
            # Need to call .load() because .open() is lazy
            grabbed.load()
        return MapRegion(coord, grabbed)

    async def async_get_area(
        self,
        corner1: MapCoord,
        corner2: MapCoord,
        tile_callback: Callable[[Union[MapRegion, str]], None],
        save_every: int = 451,
        stats_every: int = 20,
        force_rows: Optional[FrozenSet[int]] = None,
        progress: MapProgressProtocol = None,
        err_callback: Callable[[str], None] = None,
        quiet: bool = False,
    ):
        """
        Asynchronously get an area from corner1 to corner2 inclusive.

        `tile_callback` will be called for every successful tile retrieval with the fetched tile.
        Do note that on some checkpoints, `tile_callback` will be called with one of "SAVE", "ROW", or other strings;
        therefore whatever implementation `tile_callback` is, it must NOT assume that the arg is MapTile

        :param corner1: One corner of the area (inclusive)
        :param corner2: The other diametrically opposite corner of the area (inclusive)
        :param tile_callback: Function to be called back on every successful tile fetch
        :param save_every: Emit "SAVE" to tile_callback every this count
        :param stats_every: Emit stats every this count
        :param force_rows: Set of rows to be retrieved even if already seen in progress.seen
        :param progress: Map fetching progress state
        :param err_callback: Function to be called back on tile fetch error
        :param quiet: If true, try to be less chatty
        :return:
        """
        qprint = QuietablePrint(quiet)
        x1, y1 = corner1
        x2, y2 = corner2
        x_min, x_max = (x1, x2) if x1 < x2 else (x2, x1)
        y_min, y_max = (y1, y2) if y1 < y2 else (y2, y1)
        qprint(f"Fetching area ({x_min}, {y_max})..({x_max}, {y_min})...")
        if progress is None:
            progress = MapProgressProtocol()
        nonvoids_count = len(progress.regions)
        tiles_count = len(progress.seen)
        if not quiet:
            print("Generating jobs")
        if force_rows is None:
            force_rows = set()
        count = 0
        rows_processed = 0
        aborted_count = 0
        skipping = False
        y = -1
        try:
            for y in range(y_max, y_min - 1, -1):
                row_t = time.monotonic()

                tasks = []
                for x in range(x_min, x_max + 1):
                    coord = MapCoord(x, y)
                    if coord in progress.seen and y not in force_rows:
                        continue
                    tasks.append(self.async_get_region(coord, quiet=True))

                if not tasks:
                    if not skipping:
                        skipping = True
                        qprint(f"Skipping row {y} to ... ", end="", flush=True)
                    continue
                if skipping:
                    skipping = False
                    if not quiet:
                        print(y + 1)

                qprint(f"Waiting for row {y}...", end="", flush=True)
                tile: Optional[MapRegion] = None
                row_nonvoids = 0

                aborting_exception = None

                for task in asyncio.as_completed(tasks):
                    try:
                        tile = await task
                    except KeyboardInterrupt as e:
                        progress.last_fail_rows.add(y)
                        aborting_exception = e
                    except Exception as e:
                        if not isinstance(e, MapConnectionError):
                            print(str(e), flush=True)
                        if err_callback:
                            err_callback(str(e))
                        progress.last_fail_rows.add(y)
                        if aborting_exception is None:
                            qprint(f" aborting row {y}", flush=True)
                            aborted_count += 1
                            aborting_exception = e
                    # Note: We can't raise ourselves out of the loop, because if we do that we might miss exceptions
                    # happening in sunsequent completing tasks, causing another error about "Exception not handled"
                    # However, we also don't want to waste effort processing this row, so we just 'shortcircuit'
                    # the loop instead
                    if aborting_exception is not None:
                        continue

                    tile_callback(tile)
                    if not tile.is_void:
                        nonvoids_count += 1
                        row_nonvoids += 1
                    tiles_count += 1
                    count += 1
                    if count >= save_every:
                        tile_callback("SAVE")
                        count = 0

                # Here, a different situation from the previous Note. We don't want to abort the whole processing,
                # we just want to skip end-of-row processing because the row has been aborted.
                if aborting_exception is not None:
                    continue

                tile_callback("ROW")
                rows_processed += 1
                progress.last_fail_rows.discard(y)

                row_e = time.monotonic() - row_t
                qprint(f" {row_nonvoids} regions, {row_e:,.2f}s", flush=True)

                if y % stats_every == 0:
                    qprint(
                        f"# Total of {nonvoids_count:,} regions so far in {tiles_count:,} tiles",
                        end="",
                    )
                    if aborted_count:
                        qprint(f", with {aborted_count} row aborts.")
                    else:
                        qprint()
            else:
                if skipping:
                    qprint(y, flush=True)
            qprint(
                f"All requested rows have been fetched, a total of {rows_processed} new rows."
            )
        except (KeyboardInterrupt, RuntimeError):
            progress.last_fail_rows.add(y)


class MapCanvas(object):
    """
    A canvas where the map will be drawn
    """
    def __init__(
        self,
        south_west: MapCoord,
        width: int,
        height: int,
        *,
        void_image: Image.Image = None,
        initial_tiles=None,
    ):
        """
        Creates a MapCanvas object.

        :param south_west: Coordinates of the region that will be in the lower-left corner
        :param width: Width of the canvas, in pixels
        :param height: Height of the canvas, in pixels
        """
        canv_w = width * _REGION_SIZE
        canv_h = height * _REGION_SIZE
        self.canvas = Image.new("RGBA", (canv_w, canv_h), color=initial_tiles)
        self.void_image = void_image
        self.south_west = south_west
        self.width = width
        self.height = height
        self._min_x = self.south_west.x
        self._max_y = self.south_west.y + self.height - 1

    def add_region(self, region: MapRegion):
        if region.is_void and self.void_image is None:
            return
        tile_x, tile_y = region.coord
        canv_x = (tile_x - self._min_x) * _REGION_SIZE
        canv_y = (self._max_y - tile_y) * _REGION_SIZE
        self.canvas.paste(region.image, (canv_x, canv_y))

    def save_to(self, dest: Union[Path | io.IOBase], image_format: str = None, optimize: bool = True):
        if isinstance(dest, io.IOBase):
            if not image_format:
                raise ValueError("image_format must be specified if dest is a stream")
        if dest.suffix == ".png" or (image_format and image_format.casefold() == "png"):
            self.canvas.save(dest, format=image_format, optimize=optimize)
        else:
            self.canvas.save(dest, format=image_format)

    @property
    def size(self):
        return self.canvas.size


class BoundedMapFetcher(MapFetcher):
    """
    Wraps MapFetcher in a way to limit in-flight fetches.

    It does this by implementing a semaphore of a certain size, and only launches an actual fetcher job when it can
    acquire a semaphore.

    This is done to limit the concurrent hit against the SL Maps CDN, because empirical experience seems to indicate
    that if there are too many in-flight requests, we get throttled.
    """

    def __init__(self, sema_size: int, async_session: httpx.AsyncClient, retries: int = 3):
        """

        :param sema_size: Size of semaphore, which limits the number of in-flight requests
        :param async_session: The asynchronous httpx session to be used (connection pool, etc)
        :param retries: How many times to retry if request completes but we get an unexpected HTTP Status Code
        """
        super().__init__(a_session=async_session)
        self.sema = asyncio.Semaphore(sema_size)
        self.retries = retries

    async def async_fetch(self, coord: MapCoord) -> Optional[RawRegion]:
        """Perform async fetch, but won't actually start fetching if semaphore is depleted."""
        async with self.sema:
            try:
                return await self.async_get_region_raw(coord, quiet=True, retries=self.retries)
            except asyncio.CancelledError:
                print(f"{coord} cancelled")
                return None
