import argparse
import asyncio
import random
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
from simulation import DNSResolver, URLPool, simulated_fetch


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
    session: aiohttp.ClientSession | None,
    config: Config,
    shutdown_event: asyncio.Event,
    url_pool: URLPool | None = None,
    dns_resolver: DNSResolver | None = None,
):
    while not shutdown_event.is_set():
        item = await frontier.get()
        if item is None:
            await asyncio.sleep(0.01)
            continue

        host, url = item
        active_requests.inc()

        # 根據模式切換 fetch 行為
        if config.simulation_mode:
            status, body, duration, error = await simulated_fetch(
                url, config.simulation_delay_ms, dns_resolver
            )
        else:
            status, body, duration, error = await fetch(session, url, config.request_timeout)

        active_requests.dec()
        frontier.release(host)
        request_duration.observe(duration)
        pages_crawled.inc()

        # 根據模式切換連結提取行為
        links = []
        if error is None and status == 200:
            if config.simulation_mode and url_pool:
                link_count = random.randint(config.simulation_links_min, config.simulation_links_max)
                links = url_pool.get_random_links(link_count)
            else:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Web Crawler with simulation mode support")

    # 基本設定
    parser.add_argument("--max-pages", type=int, help="Maximum pages to crawl")
    parser.add_argument("--workers", type=int, help="Number of workers")
    parser.add_argument("--max-per-host", type=int, help="Max concurrent requests per host")

    # 模擬模式
    parser.add_argument("--simulation", action="store_true", help="Enable simulation mode (no real HTTP requests)")
    parser.add_argument("--delay-ms", type=int, help="Simulated request delay in milliseconds")
    parser.add_argument("--url-pool", type=str, help="Path to URL pool file for simulation")

    # 優化選項（預留）
    parser.add_argument("--bloom", action="store_true", help="Use Bloom Filter for URL deduplication")
    parser.add_argument("--dns-cache", action="store_true", help="Enable DNS caching")

    return parser.parse_args()


async def main():
    args = parse_args()
    config = Config()

    # 套用 CLI 參數
    if args.max_pages:
        config.max_pages = args.max_pages
    if args.workers:
        config.num_workers = args.workers
    if args.max_per_host:
        config.max_per_host = args.max_per_host
    if args.simulation:
        config.simulation_mode = True
    if args.delay_ms:
        config.simulation_delay_ms = args.delay_ms
    if args.url_pool:
        config.url_pool_file = args.url_pool
    if args.bloom:
        config.use_bloom_filter = True
    if args.dns_cache:
        config.use_dns_cache = True

    # 顯示設定
    mode = "SIMULATION" if config.simulation_mode else "REAL"
    print(f"=== Crawler Config ({mode}) ===")
    print(f"Seeds: {len(config.seed_urls)} domains")
    print(f"Workers: {config.num_workers}, MaxPerHost: {config.max_per_host}")
    print(f"MaxPages: {config.max_pages}")
    if config.simulation_mode:
        print(f"Delay: {config.simulation_delay_ms}ms, Links: {config.simulation_links_min}-{config.simulation_links_max}")
    print(f"Options: bloom={config.use_bloom_filter}, dns_cache={config.use_dns_cache}")
    print("=" * 35 + "\n")

    # 載入 URL 池和 DNS resolver（模擬模式時）
    url_pool: URLPool | None = None
    dns_resolver: DNSResolver | None = None
    if config.simulation_mode:
        url_pool = URLPool(config.url_pool_file)
        dns_resolver = DNSResolver(use_cache=config.use_dns_cache)
        print(f"DNS resolver: cache={'enabled' if config.use_dns_cache else 'disabled'}\n")

    start_metrics_server(config.metrics_port)

    frontier = Frontier(config.max_per_host)
    results: asyncio.Queue[Result] = asyncio.Queue(maxsize=1000)
    shutdown_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: shutdown_event.set())

    for url in config.seed_urls:
        await frontier.add(url)

    start_time = time.monotonic()

    # 模擬模式不需要真實的 HTTP session
    if config.simulation_mode:
        workers = [
            asyncio.create_task(
                worker(i, frontier, results, None, config, shutdown_event, url_pool, dns_resolver)
            )
            for i in range(config.num_workers)
        ]

        processor = asyncio.create_task(result_processor(frontier, results, config, shutdown_event))
        crawled = await processor

        shutdown_event.set()
        await asyncio.gather(*workers, return_exceptions=True)
    else:
        connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            workers = [
                asyncio.create_task(
                    worker(i, frontier, results, session, config, shutdown_event, url_pool, dns_resolver)
                )
                for i in range(config.num_workers)
            ]

            processor = asyncio.create_task(result_processor(frontier, results, config, shutdown_event))
            crawled = await processor

            shutdown_event.set()
            await asyncio.gather(*workers, return_exceptions=True)

    elapsed = time.monotonic() - start_time
    queued, _, domains = frontier.stats()
    print(f"\n=== Done ===")
    print(f"Crawled: {crawled} pages in {elapsed:.1f}s ({crawled/elapsed:.1f} QPS)")
    print(f"Queue remaining: {queued} (across {domains} domains)")

    # 印出 DNS 統計（模擬模式時）
    if dns_resolver:
        stats = dns_resolver.stats
        print(f"DNS: {stats['hits']} hits, {stats['misses']} misses "
              f"({stats['hit_rate']:.1%} hit rate, {stats['cache_size']} cached)")


if __name__ == "__main__":
    asyncio.run(main())
