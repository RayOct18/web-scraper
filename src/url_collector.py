"""
URL Collector - 收集真實 URL 建立 URL 池

用途：先跑一次真實爬蟲，收集 URL 存成 JSON 檔案，
之後模擬測試時可以從這個 URL 池中隨機選取連結。

執行方式：
    uv run python -m src.url_collector --max-pages 5000
"""

import argparse
import asyncio
import json
import time
from collections import defaultdict
from urllib.parse import urlparse

import aiohttp

from src.config import Config
from src.dispatcher import Dispatcher, Result
from src.frontier import Frontier
from src.parser import extract_links


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
    collected_urls: dict[str, list[str]],
) -> int:
    """處理結果並收集 URL"""
    crawled = 0
    empty_count = 0

    while crawled < config.max_pages:
        try:
            result = await asyncio.wait_for(results.get(), timeout=0.5)
            empty_count = 0
        except asyncio.TimeoutError:
            empty_count += 1
            if empty_count > 10:
                print(f"No more URLs, stopped at {crawled} pages")
                break
            continue

        crawled += 1

        if result.error:
            print(f"[{crawled}] ERROR {result.url}: {result.error}")
        else:
            links_count = len(result.links)
            print(f"[{crawled}] {result.status} {result.url} ({result.duration:.2f}s, {links_count} links)")

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
    parser.add_argument(
        "--max-pages", type=int, default=5000, help="Maximum pages to crawl"
    )
    parser.add_argument(
        "--output", type=str, default="url_pool.json", help="Output file path"
    )
    parser.add_argument("--workers", type=int, default=10, help="Number of workers")
    parser.add_argument(
        "--max-per-host", type=int, default=10, help="Max concurrent requests per host"
    )
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

    frontier = Frontier(config.max_per_host)
    results: asyncio.Queue[Result] = asyncio.Queue(maxsize=1000)
    collected_urls: dict[str, list[str]] = defaultdict(list)

    for url in config.seed_urls:
        await frontier.add(url)

    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        # 建立 fetcher 和 link_extractor
        async def fetcher(url: str):
            return await fetch(session, url, config.request_timeout)

        def link_extractor(body: str, url: str) -> list[str]:
            return extract_links(body, url)

        # 使用 Dispatcher
        dispatcher = Dispatcher(
            frontier=frontier,
            fetcher=fetcher,
            link_extractor=link_extractor,
            results=results,
            num_workers=config.num_workers,
        )

        dispatcher_task = asyncio.create_task(dispatcher.run())
        crawled = await result_processor(frontier, results, config, collected_urls)

        # Cleanup
        dispatcher.stop()
        dispatcher_task.cancel()
        await asyncio.gather(dispatcher_task, return_exceptions=True)

    print(f"\nCrawled: {crawled} pages")
    save_url_pool(collected_urls, args.output)


if __name__ == "__main__":
    asyncio.run(main())
