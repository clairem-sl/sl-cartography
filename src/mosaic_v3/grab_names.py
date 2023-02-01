import asyncio
import httpx

from sl_maptools import MapCoord
from sl_maptools.cap_fetcher import BoundedNameFetcher, CookedTile


CONN_LIMIT = 30
SEMA_SIZE = 100
BATCH_WAIT = 5


async def async_main():
    limits = httpx.Limits(max_connections=CONN_LIMIT, max_keepalive_connections=CONN_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=10.0, http2=False) as client:
        fetcher = BoundedNameFetcher(SEMA_SIZE, client, cooked=True)
        tasks = []
        coords = [MapCoord(x, y) for x in range(950, 1050) for y in range(950, 1050)]
        for c in coords:
            tasks.append(asyncio.create_task(fetcher.async_fetch(c), name=f"fetch-{c}"))
        pending_tasks = [1]
        while pending_tasks:
            done, pending_tasks = await asyncio.wait(tasks, timeout=BATCH_WAIT)
            c = 0
            for c, fut in enumerate(done, start=1):
                rslt: CookedTile = fut.result()
                if rslt.result:
                    if rslt.result.isdigit():
                        print(f"\n{rslt}")
                    else:
                        print(f"{rslt}", end=" ", flush=True)
            print(f"\n{c} results -----")
            tasks = pending_tasks


def main():
    asyncio.run(async_main())


if __name__ == '__main__':
    main()
