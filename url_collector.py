"""
URL Collector - 收集真實 URL 建立 URL 池

用途：先跑一次真實爬蟲，收集 URL 存成 JSON 檔案，
之後模擬測試時可以從這個 URL 池中隨機選取連結。

執行方式：
    uv run python url_collector.py --max-pages 50000
"""

import argparse
import asyncio
import json
import signal
import time
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse

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
    collected_urls: dict[str, list[str]],
) -> int:
    """處理結果並收集 URL"""
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

        # 收集所有發現的連結（按 host 分類）
        for link in result.links:
            parsed = urlparse(link)
            host = parsed.netloc
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"

            # 只保留路徑（不重複完整 URL）
            if path not in collected_urls[host]:
                collected_urls[host].append(path)

            # 同時加入 frontier 繼續爬取
            await frontier.add(link)

        queued, active, domains = frontier.stats()
        queue_size.set(queued)

        if crawled >= config.max_pages:
            shutdown_event.set()
            break

    return crawled


def save_url_pool(collected_urls: dict[str, list[str]], output_file: str):
    """儲存 URL 池到 JSON 檔案"""
    total = sum(len(paths) for paths in collected_urls.values())

    data = {
        "total": total,
        "hosts": len(collected_urls),
        "urls_by_host": dict(collected_urls),
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {total} URLs from {len(collected_urls)} hosts to {output_file}")


async def main():
    parser = argparse.ArgumentParser(description="Collect URLs for simulation testing")
    parser.add_argument("--max-pages", type=int, default=5000, help="Maximum pages to crawl")
    parser.add_argument("--output", type=str, default="url_pool.json", help="Output file path")
    parser.add_argument("--workers", type=int, default=10, help="Number of workers")
    parser.add_argument("--max-per-host", type=int, default=10, help="Max concurrent requests per host")
    args = parser.parse_args()

    config = Config()
    config.max_pages = args.max_pages
    config.num_workers = args.workers
    config.max_per_host = args.max_per_host

    print("=== URL Collector ===")
    print(f"Seeds: {len(config.seed_urls)} domains")
    print(f"Workers: {config.num_workers}, MaxPerHost: {config.max_per_host}")
    print(f"MaxPages: {config.max_pages}")
    print(f"Output: {args.output}")
    print("=====================\n")

    start_metrics_server(config.metrics_port)

    frontier = Frontier(config.max_per_host)
    results: asyncio.Queue[Result] = asyncio.Queue(maxsize=1000)
    shutdown_event = asyncio.Event()
    collected_urls: dict[str, list[str]] = defaultdict(list)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: shutdown_event.set())

    for url in config.seed_urls:
        await frontier.add(url)

    start_time = time.monotonic()

    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        workers = [
            asyncio.create_task(worker(i, frontier, results, session, config, shutdown_event))
            for i in range(config.num_workers)
        ]

        processor = asyncio.create_task(
            result_processor(frontier, results, config, shutdown_event, collected_urls)
        )

        crawled = await processor

        shutdown_event.set()
        await asyncio.gather(*workers, return_exceptions=True)

    elapsed = time.monotonic() - start_time
    queued, _, domains = frontier.stats()

    print(f"\n=== Done ===")
    print(f"Crawled: {crawled} pages in {elapsed:.1f}s ({crawled/elapsed:.1f} QPS)")
    print(f"Queue remaining: {queued} (across {domains} domains)")

    # 儲存 URL 池
    save_url_pool(collected_urls, args.output)


if __name__ == "__main__":
    asyncio.run(main())
