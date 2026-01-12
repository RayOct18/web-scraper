import argparse
import asyncio
import random
import time

import aiohttp

from src.config import Config
from src.dispatcher import Dispatcher, Result
from src.frontier import Frontier
from src.metrics import (
    get_labeled_metrics,
    set_labels,
    start_metrics_server,
)
from src.parser import extract_links
from src.simulation import DNSResolver, URLPool, simulated_fetch


async def fetch(
    session: aiohttp.ClientSession,
    url: str,
    timeout: float,
) -> tuple[int, str, float, str | None]:
    start = time.monotonic()
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            body = await resp.text()
            return resp.status, body, time.monotonic() - start, None
    except Exception as e:
        return 0, "", time.monotonic() - start, str(e)


async def result_processor(
    frontier: Frontier,
    results: asyncio.Queue[Result],
    config: Config,
) -> int:
    # 取得帶 labels 的 metrics
    _, _, queue_size, _ = get_labeled_metrics()

    crawled = 0

    while crawled < config.max_pages:
        try:
            result = await asyncio.wait_for(results.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        crawled += 1

        if result.error:
            print(f"[{crawled}] ERROR {result.url}: {result.error}")
        else:
            link_count = len(result.links)
            print(
                f"[{crawled}] {result.status} {result.url} "
                f"({result.duration:.2f}s, {link_count} links)"
            )

        for link in result.links:
            await frontier.add(link)

        queued, active, domains = frontier.stats()
        queue_size.set(queued)

    return crawled


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Web Crawler with simulation mode support"
    )

    # 基本設定
    parser.add_argument("--max-pages", type=int, help="Maximum pages to crawl")
    parser.add_argument("--workers", type=int, help="Number of workers")
    parser.add_argument(
        "--max-per-host", type=int, help="Max concurrent requests per host"
    )

    # 模擬模式
    parser.add_argument(
        "--simulation",
        action="store_true",
        help="Enable simulation mode (no real HTTP requests)",
    )
    parser.add_argument(
        "--delay-ms", type=int, help="Simulated request delay in milliseconds"
    )
    parser.add_argument(
        "--url-pool", type=str, help="Path to URL pool file for simulation"
    )

    # 優化選項（預留）
    parser.add_argument(
        "--bloom", action="store_true", help="Use Bloom Filter for URL deduplication"
    )
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
        print(
            f"Delay: {config.simulation_delay_ms}ms, Links: "
            f"{config.simulation_links_min}-{config.simulation_links_max}"
        )
    print(f"Options: bloom={config.use_bloom_filter}, dns_cache={config.use_dns_cache}")
    print("=" * 35 + "\n")

    # 載入 URL 池和 DNS resolver（模擬模式時）
    url_pool: URLPool | None = None
    dns_resolver: DNSResolver | None = None
    if config.simulation_mode:
        url_pool = URLPool(config.url_pool_file)
        dns_resolver = DNSResolver(use_cache=config.use_dns_cache)
        print(
            f"DNS resolver: cache={'enabled' if config.use_dns_cache else 'disabled'}\n"
        )

    # 設定 metrics labels
    set_labels(
        mode="simulation" if config.simulation_mode else "real",
        dns_cache=config.use_dns_cache,
        workers=config.num_workers,
    )

    start_metrics_server(config.metrics_port)

    frontier = Frontier(config.max_per_host)
    results: asyncio.Queue[Result] = asyncio.Queue(maxsize=1000)

    for url in config.seed_urls:
        await frontier.add(url)

    start_time = time.monotonic()

    # 建立 fetcher 和 link_extractor (根據模式)
    if config.simulation_mode:
        async def fetcher(url: str):
            return await simulated_fetch(url, config.simulation_delay_ms, dns_resolver)

        def link_extractor(body: str, url: str) -> list[str]:
            link_count = random.randint(
                config.simulation_links_min, config.simulation_links_max
            )
            return url_pool.get_random_links(link_count)

        # 建立 Dispatcher
        dispatcher = Dispatcher(
            frontier=frontier,
            fetcher=fetcher,
            link_extractor=link_extractor,
            results=results,
            num_workers=config.num_workers,
        )

        # 啟動 dispatcher (會自動啟動所有 workers)
        dispatcher_task = asyncio.create_task(dispatcher.run())

        # 處理結果
        crawled = await result_processor(frontier, results, config)

        # Cleanup
        dispatcher.stop()
        dispatcher_task.cancel()
        await asyncio.gather(dispatcher_task, return_exceptions=True)
    else:
        connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            async def fetcher(url: str):
                return await fetch(session, url, config.request_timeout)

            def link_extractor(body: str, url: str) -> list[str]:
                return extract_links(body, url)

            # 建立 Dispatcher
            dispatcher = Dispatcher(
                frontier=frontier,
                fetcher=fetcher,
                link_extractor=link_extractor,
                results=results,
                num_workers=config.num_workers,
            )

            # 啟動 dispatcher
            dispatcher_task = asyncio.create_task(dispatcher.run())

            # 處理結果
            crawled = await result_processor(frontier, results, config)

            # Cleanup
            dispatcher.stop()
            dispatcher_task.cancel()
            await asyncio.gather(dispatcher_task, return_exceptions=True)

    elapsed = time.monotonic() - start_time
    queued, _, domains = frontier.stats()
    print("\n=== Done ===")
    print(f"Crawled: {crawled} pages in {elapsed:.1f}s ({crawled / elapsed:.1f} QPS)")
    print(f"Queue remaining: {queued} (across {domains} domains)")


if __name__ == "__main__":
    asyncio.run(main())
