"""
URL Collector - 收集真實 URL 建立 URL 池

用途：先跑一次真實爬蟲，收集 URL 存成 JSON 檔案，
之後模擬測試時可以從這個 URL 池中隨機選取連結。

執行方式：
    uv run python -m src.url_collector --max-pages 5000
"""

import asyncio
import json
from collections import defaultdict
from typing import Annotated
from urllib.parse import urlparse

import typer

from prometheus_client import CollectorRegistry

from src.config import Config
from src.fetcher import HttpFetcher
from src.frontier import Frontier
from src.metrics import Metrics
from src.parser import extract_links
from src.worker import Result, run_workers

app = typer.Typer(help="Collect URLs for simulation testing")


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


@app.command()
def main(
    max_pages: Annotated[int, typer.Option(help="Maximum pages to crawl")] = 5000,
    output: Annotated[str, typer.Option(help="Output file path")] = "url_pool.json",
    workers: Annotated[int, typer.Option(help="Number of workers")] = 10,
    max_per_host: Annotated[
        int, typer.Option(help="Max concurrent requests per host")
    ] = 10,
):
    config = Config(
        max_pages=max_pages,
        num_workers=workers,
        max_per_host=max_per_host,
    )

    print("=== URL Collector ===")
    print(f"Seeds: {len(config.seed_urls)} domains")
    print(f"Workers: {config.num_workers}, MaxPerHost: {config.max_per_host}")
    print(f"MaxPages: {config.max_pages}")
    print(f"Output: {output}")
    print("=====================\n")

    asyncio.run(_main(config, output))


async def _main(config: Config, output: str):
    collected_urls: dict[str, list[str]] = defaultdict(list)
    # Use empty registry - metrics work but aren't collected/scraped
    metrics = Metrics(
        mode="collector",
        dns_cache=False,
        workers=config.num_workers,
        registry=CollectorRegistry(),
    )
    frontier = Frontier(
        max_per_host=config.max_per_host, delay_per_host=0, metrics=metrics
    )

    for url in config.seed_urls:
        await frontier.add_url(url)

    # 進度追蹤
    crawled = 0
    done_event = asyncio.Event()

    async def on_result(result: Result) -> None:
        nonlocal crawled
        crawled += 1

        if result.error:
            print(f"[{crawled}] ERROR {result.url}: {result.error}")
        else:
            links_count = len(result.links)
            print(
                f"[{crawled}] {result.status} {result.url} ({result.duration:.2f}s, {links_count} links)"
            )

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

        if crawled >= config.max_pages:
            done_event.set()

    async with HttpFetcher(timeout=config.request_timeout) as http_fetcher:
        link_extractor = lambda body, url: extract_links(body, url)

        worker_tasks = await run_workers(
            frontier=frontier,
            fetcher=http_fetcher.fetch,
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

    print(f"\nCrawled: {crawled} pages")
    save_url_pool(collected_urls, output)


if __name__ == "__main__":
    app()
