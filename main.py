import asyncio
import signal
import time
from dataclasses import dataclass

import aiohttp

from config import Config
from frontier import Frontier
from metrics import (
    active_requests,
    pages_crawled,
    queue_size,
    request_duration,
    start_metrics_server,
)
from parser import extract_links


@dataclass
class Result:
    url: str
    host: str
    status: int
    links: list[str]
    duration: float
    error: str | None = None


async def fetch(
    session: aiohttp.ClientSession,
    url: str,
    timeout: float,
) -> tuple[int, str, float, str | None]:
    start = time.monotonic()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            body = await resp.text()
            return resp.status, body, time.monotonic() - start, None
    except Exception as e:
        return 0, "", time.monotonic() - start, str(e)


async def worker(
    worker_id: int,
    frontier: Frontier,
    results: asyncio.Queue[Result],
    session: aiohttp.ClientSession,
    config: Config,
    shutdown_event: asyncio.Event,
):
    while not shutdown_event.is_set():
        item = await frontier.get()
        if item is None:
            await asyncio.sleep(0.01)
            continue

        host, url = item
        active_requests.inc()

        status, body, duration, error = await fetch(session, url, config.request_timeout)

        active_requests.dec()
        frontier.release(host)
        request_duration.observe(duration)
        pages_crawled.inc()

        links = []
        if error is None and status == 200:
            links = extract_links(body, url)

        await results.put(Result(
            url=url,
            host=host,
            status=status,
            links=links,
            duration=duration,
            error=error,
        ))


async def result_processor(
    frontier: Frontier,
    results: asyncio.Queue[Result],
    config: Config,
    shutdown_event: asyncio.Event,
) -> int:
    crawled = 0

    while not shutdown_event.is_set() or not results.empty():
        try:
            result = await asyncio.wait_for(results.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        crawled += 1

        if result.error:
            print(f"[{crawled}] ERROR {result.url}: {result.error}")
        else:
            print(f"[{crawled}] {result.status} {result.url} ({result.duration:.2f}s, {len(result.links)} links)")

        for link in result.links:
            await frontier.add(link)

        queued, active, domains = frontier.stats()
        queue_size.set(queued)

        if crawled >= config.max_pages:
            shutdown_event.set()
            break

    return crawled


async def main():
    config = Config()

    print("=== Crawler Config ===")
    print(f"Seeds: {len(config.seed_urls)} domains")
    print(f"Workers: {config.num_workers}, MaxPerHost: {config.max_per_host}")
    print(f"MaxPages: {config.max_pages}")
    print("======================\n")

    start_metrics_server(config.metrics_port)

    frontier = Frontier(config.max_per_host)
    results: asyncio.Queue[Result] = asyncio.Queue(maxsize=1000)
    shutdown_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: shutdown_event.set())

    for url in config.seed_urls:
        await frontier.add(url)

    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        workers = [
            asyncio.create_task(worker(i, frontier, results, session, config, shutdown_event))
            for i in range(config.num_workers)
        ]

        processor = asyncio.create_task(result_processor(frontier, results, config, shutdown_event))

        crawled = await processor

        shutdown_event.set()
        await asyncio.gather(*workers, return_exceptions=True)

    queued, _, domains = frontier.stats()
    print(f"\n=== Done ===")
    print(f"Crawled: {crawled} pages")
    print(f"Queue remaining: {queued} (across {domains} domains)")


if __name__ == "__main__":
    asyncio.run(main())
