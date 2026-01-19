"""
Worker Module - Pull-based worker implementation

Workers pull work directly from Frontier, eliminating the intermediate queue.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.frontier import Frontier
    from src.metrics import Metrics


@dataclass
class Result:
    url: str
    host: str
    status: int
    links: list[str]
    duration: float
    error: str | None = None


async def worker(
    frontier: Frontier,
    fetcher: Callable[[str], Awaitable[tuple[int, str, float, str | None]]],
    link_extractor: Callable[[str, str], list[str]],
    on_result: Callable[[Result], Awaitable[None]] | None,
    metrics: Metrics,
    worker_id: int,
) -> None:
    """Single worker that pulls work from frontier."""
    while True:
        urls = await frontier.get_next_url()

        if urls is None:
            await asyncio.sleep(0.1)
            continue

        host, url = urls

        try:
            metrics.active_requests.inc()

            # Fetch the URL
            status, body, duration, error = await fetcher(url)

            metrics.request_duration.observe(duration)
            metrics.pages_crawled.inc()

            # Track success/failure
            if error is None and 200 <= status < 300:
                metrics.fetch_success.inc()
            else:
                metrics.fetch_failure.inc()

            # Extract links if successful
            links = []
            if error is None and status == 200:
                links = link_extractor(body, url)

            # Add links to frontier directly
            for link in links:
                await frontier.add_url(link)

            # Create result
            result = Result(
                url=url,
                host=host,
                status=status,
                links=links,
                duration=duration,
                error=error,
            )

            # Call callback if provided
            if on_result is not None:
                await on_result(result)
        finally:
            metrics.active_requests.dec()
            await frontier.release(host)


async def run_workers(
    frontier: Frontier,
    fetcher: Callable[[str], Awaitable[tuple[int, str, float, str | None]]],
    link_extractor: Callable[[str, str], list[str]],
    on_result: Callable[[Result], Awaitable[None]] | None,
    metrics: Metrics,
    num_workers: int,
) -> list[asyncio.Task]:
    """Start all workers and return their tasks."""
    return [
        asyncio.create_task(
            worker(frontier, fetcher, link_extractor, on_result, metrics, i)
        )
        for i in range(num_workers)
    ]
