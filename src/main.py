import asyncio
import random
import time
from typing import Annotated

import typer

from src.config import Config
from src.fetcher import HttpFetcher, SimulatedFetcher
from src.frontier import Frontier
from src.metrics import Metrics, start_metrics_server
from src.parser import extract_links
from src.simulation import DNSResolver, URLPool
from src.worker import Result, run_workers

app = typer.Typer(help="Web Crawler with simulation mode support")


@app.command()
def main(
    max_pages: Annotated[int, typer.Option(help="Maximum pages to crawl")] = 30000,
    workers: Annotated[int, typer.Option(help="Number of workers")] = 20,
    max_per_host: Annotated[
        int, typer.Option(help="Max concurrent requests per host")
    ] = 10,
    delay_per_host: Annotated[
        float, typer.Option(help="Delay in seconds between requests to same host")
    ] = 0.5,
    simulation: Annotated[
        bool, typer.Option(help="Enable simulation mode (no real HTTP requests)")
    ] = False,
    delay_ms: Annotated[
        int, typer.Option(help="Simulated request delay in milliseconds")
    ] = 50,
    url_pool: Annotated[
        str, typer.Option(help="Path to URL pool file for simulation")
    ] = "url_pool.json",
    bloom: Annotated[
        bool, typer.Option(help="Use Bloom Filter for URL deduplication")
    ] = False,
    dns_cache: Annotated[bool, typer.Option(help="Enable DNS caching")] = False,
):
    config = Config(
        max_pages=max_pages,
        num_workers=workers,
        max_per_host=max_per_host,
        delay_per_host=delay_per_host,
        simulation_mode=simulation,
        simulation_delay_ms=delay_ms,
        url_pool_file=url_pool,
        use_bloom_filter=bloom,
        use_dns_cache=dns_cache,
    )
    asyncio.run(_main(config))


async def _main(config: Config):
    # 顯示設定
    mode = "SIMULATION" if config.simulation_mode else "REAL"
    print(f"=== Crawler Config ({mode}) ===")
    print(f"Seeds: {len(config.seed_urls)} domains")
    print(f"Workers: {config.num_workers}, MaxPerHost: {config.max_per_host}")
    print(f"MaxPages: {config.max_pages}, DelayPerHost: {config.delay_per_host}s")
    if config.simulation_mode:
        print(
            f"Delay: {config.simulation_delay_ms}ms, Links: "
            f"{config.simulation_links_min}-{config.simulation_links_max}"
        )
    print(f"Options: bloom={config.use_bloom_filter}, dns_cache={config.use_dns_cache}")
    print("=" * 35 + "\n")

    # 建立 metrics
    metrics = Metrics(
        mode="simulation" if config.simulation_mode else "real",
        dns_cache=config.use_dns_cache,
        workers=config.num_workers,
    )
    start_metrics_server(config.metrics_port)

    frontier = Frontier(
        max_per_host=config.max_per_host,
        delay_per_host=config.delay_per_host,
        metrics=metrics,
        use_bloom_filter=config.use_bloom_filter,
        bloom_capacity=config.bloom_capacity,
        bloom_error_rate=config.bloom_error_rate,
    )

    for url in config.seed_urls:
        await frontier.add_url(url)

    start_time = time.monotonic()

    # 建立 fetcher 和 link_extractor (根據模式)
    http_fetcher = HttpFetcher(timeout=config.request_timeout)
    if config.simulation_mode:
        pool = URLPool(config.url_pool_file)
        dns_resolver = DNSResolver(use_cache=config.use_dns_cache, metrics=metrics)
        print(
            f"DNS resolver: cache={'enabled' if config.use_dns_cache else 'disabled'}\n"
        )
        http_fetcher = SimulatedFetcher(
            delay_ms=config.simulation_delay_ms,
            dns_resolver=dns_resolver,
        )
        fetcher_fn = http_fetcher.fetch
        link_extractor = lambda body, url: pool.get_random_links(
            random.randint(config.simulation_links_min, config.simulation_links_max)
        )
    else:
        fetcher_fn = http_fetcher.fetch
        link_extractor = lambda body, url: extract_links(body, url)

    # 進度追蹤
    crawled = 0
    done_event = asyncio.Event()

    async def on_result(result: Result) -> None:
        nonlocal crawled
        crawled += 1

        if result.error:
            print(f"[{crawled}] ERROR {result.url}: {result.error}")
        else:
            link_count = len(result.links)
            print(
                f"[{crawled}] {result.status} {result.url} "
                f"({result.duration:.2f}s, {link_count} links)"
            )

        if crawled >= config.max_pages:
            done_event.set()

    async with http_fetcher:
        # Start workers
        worker_tasks = await run_workers(
            frontier=frontier,
            fetcher=fetcher_fn,
            link_extractor=link_extractor,
            on_result=on_result,
            metrics=metrics,
            num_workers=config.num_workers,
        )

        # Wait until done
        await done_event.wait()

        # Cancel workers
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    elapsed = time.monotonic() - start_time
    print("\n=== Done ===")
    print(f"Crawled: {crawled} pages in {elapsed:.1f}s ({crawled / elapsed:.1f} QPS)")


if __name__ == "__main__":
    app()
