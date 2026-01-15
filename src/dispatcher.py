"""
Dispatcher Module - Worker 協調與執行

負責：
1. 管理 worker pool (idle workers queue)
2. 分配工作給 workers
3. 執行 worker 邏輯
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable, TYPE_CHECKING

from src.frontier import Frontier

if TYPE_CHECKING:
    from src.metrics import Metrics, NullMetrics


@dataclass
class Result:
    url: str
    host: str
    status: int
    links: list[str]
    duration: float
    error: str | None = None


class Dispatcher:
    """Worker 協調 - 負責 worker pool 管理和工作分配"""

    def __init__(
        self,
        frontier: Frontier,
        fetcher: Callable[[str], Awaitable[tuple[int, str, float, str | None]]],
        link_extractor: Callable[[str, str], list[str]],
        results: asyncio.Queue[Result],
        num_workers: int,
        metrics: Metrics | NullMetrics | None = None,
    ):
        self.frontier = frontier
        self.fetcher = fetcher
        self.link_extractor = link_extractor
        self.results = results
        self.num_workers = num_workers

        # Metrics (use NullMetrics if not provided)
        if metrics is None:
            metrics = NullMetrics()
        self.metrics = metrics

        # 共享 work queue，背壓控制
        self.work_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(
            maxsize=num_workers * 2
        )

        self._running = False

    async def run(self):
        """Start dispatcher and all workers."""
        self._running = True

        # Start worker tasks
        worker_tasks = [
            asyncio.create_task(self._worker_loop()) for _ in range(self.num_workers)
        ]

        # Start dispatcher loop
        dispatcher_task = asyncio.create_task(self._dispatcher_loop())

        # Wait for all (they run until stopped)
        await asyncio.gather(dispatcher_task, *worker_tasks, return_exceptions=True)

    async def _dispatcher_loop(self):
        """Dispatch work to workers via shared queue."""
        while self._running:
            work = await self.frontier.get_work()

            if work is None:
                await asyncio.sleep(0.01)
                continue

            await self.work_queue.put(work)

    async def _worker_loop(self):
        """Worker execution loop."""
        while self._running:
            try:
                host, url = await asyncio.wait_for(self.work_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            try:
                self.metrics.active_requests.inc()

                # Fetch the URL
                status, body, duration, error = await self.fetcher(url)

                self.metrics.request_duration.observe(duration)
                self.metrics.pages_crawled.inc()

                # Extract links if successful
                links = []
                if error is None and status == 200:
                    links = self.link_extractor(body, url)

                # Put result
                await self.results.put(
                    Result(
                        url=url,
                        host=host,
                        status=status,
                        links=links,
                        duration=duration,
                        error=error,
                    )
                )
            finally:
                self.metrics.active_requests.dec()
                # Release rate limit
                self.frontier.release(host)

    def stop(self):
        """Stop dispatcher and workers."""
        self._running = False
