# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# fmt: off
import platform
import asyncio
# uvloop only works with CPython on Linux
if platform.system() == "Linux" and platform.python_implementation() == "CPython":
    # noinspection PyPackageRequirements
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
else:
    uvloop = None
# fmt: on

import time
from pathlib import Path
from typing import Set, Iterable, Dict

import httpx
from sl_maptools.fetcher import MapFetcher, MapCanvas, MapConnectionError
from sl_maptools import MapCoord, MapTile, MapBounds
from sl_maptools.knowns import KNOWN_AREAS

SAVE_DIR = Path("~/Pictures/SLMap/Carto").expanduser()
CONN_LIMIT = 20


class CartographerError(RuntimeError):
    pass


class Cartographer(object):
    def __init__(self, x_left: int, y_bott: int, x_right: int, y_top: int):
        self.x_left = x_left
        self.x_right = x_right
        self.y_bott = y_bott
        self.y_top = y_top
        width = x_right - x_left + 1
        height = y_top - y_bott + 1
        self.canvas = MapCanvas(MapCoord(x_left, y_bott), width, height)

        self._regions_data: Dict[MapCoord, MapTile] = {}

    def add_tile(self, tile: MapTile):
        self.canvas.add_tile(tile)
        self._regions_data[tile.coord] = tile

    def save(self, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.canvas.save_to(dest)

    async def fetch(
        self,
        skip_coords: Set[MapCoord] = None,
        skip_subareas: Iterable[MapBounds] = None,
        conn_limit: int = CONN_LIMIT,
        retries: int = 5,
        retry_pause: float = 3.0,
    ):
        skip_coords = skip_coords or set()
        skip_subareas = skip_subareas or []

        def skip_this(x, y):
            co = MapCoord(x, y)
            if co in skip_coords:
                return True
            return any(map(lambda a: co in a, skip_subareas))

        coords_to_fetch = {
            MapCoord(x, y)
            for y in range(self.y_bott, self.y_top + 1)
            for x in range(self.x_left, self.x_right + 1)
            if not skip_this(x, y)
        }
        limits = httpx.Limits(max_connections=conn_limit)
        async with httpx.AsyncClient(limits=limits, http2=True) as client:
            fetcher = MapFetcher(a_session=client)
            print(f"{len(coords_to_fetch)} tiles to process", end="", flush=True)
            for _ in range(0, retries):
                tasks = [fetcher.async_get_tile(coord) for coord in coords_to_fetch]
                for task in asyncio.as_completed(tasks):
                    try:
                        result: MapTile = await task
                        self.add_tile(result)
                        coords_to_fetch.discard(result.coord)
                    except MapConnectionError:
                        pass
                if not coords_to_fetch:
                    break
                print("\nGot errors, retrying...", end="", flush=True)
                time.sleep(retry_pause)
            else:
                raise CartographerError("Retries exceeded")
            print()


def main():
    start_t = time.monotonic()

    for selector, area in KNOWN_AREAS.items():
        fetch_t = time.monotonic()
        print(f"\n===== Fetching {selector} =====")
        cartographer = Cartographer(*area)
        asyncio.run(cartographer.fetch())

        print("Fetching done, saving ... ", end="")
        save_t = time.monotonic()
        cartographer.save(SAVE_DIR / f"{selector}.png")
        print(f"{time.monotonic() - save_t:,.2f} seconds")

        print(f"{selector} ALL DONE. Image size is", cartographer.canvas.size)
        print(f"  Finished in {time.monotonic() - fetch_t:,.2f} seconds.")

    print()
    print("=" * 40)
    print(f"{time.monotonic() - start_t:,.2f}s in total")


if __name__ == "__main__":
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    main()
