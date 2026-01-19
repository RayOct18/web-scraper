from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pybloom_live import BloomFilter

if TYPE_CHECKING:
    from src.metrics import Metrics


class Frontier:
    """URL 管理 - 負責 dedup、per-host queues、rate limiting (concurrent + time-based)"""

    def __init__(
        self,
        max_per_host: int,
        delay_per_host: float = 1.0,
        *,
        metrics: Metrics,
        use_bloom_filter: bool = False,
        bloom_capacity: int = 100_000,
        bloom_error_rate: float = 0.01,
    ):
        self.max_per_host = max_per_host
        self.delay_per_host = delay_per_host
        self._metrics = metrics

        # URL deduplication
        if use_bloom_filter:
            self.seen: set[str] | BloomFilter = BloomFilter(
                capacity=bloom_capacity, error_rate=bloom_error_rate
            )
            self._bloom_full_warned = False
        else:
            self.seen = set()
            self._bloom_full_warned = False  # Not used, but keeps interface consistent

        # Per-host queues and rate limiting
        self.host_queues: dict[str, asyncio.Queue[str]] = defaultdict(asyncio.Queue)
        self.host_active: dict[str, int] = defaultdict(int)
        self.last_access: dict[str, float] = {}

        self._lock = asyncio.Lock()  # Protects get_work state

    async def add_url(self, url: str):
        """Add a URL to the frontier."""
        if url in self.seen:
            return
        try:
            self.seen.add(url)
        except IndexError:
            # BloomFilter at capacity - warn once and skip
            if not self._bloom_full_warned:
                print("Warning: BloomFilter at capacity, skipping new URLs")
                self._bloom_full_warned = True
            return
        host = urlparse(url).netloc or "unknown"
        await self.host_queues[host].put(url)
        self._metrics.queue_size.inc()

    async def get_next_url(self) -> tuple[str, str] | None:
        """Get available work using round-robin with time-based politeness."""
        async with self._lock:
            now = time.monotonic()

            for host, queue in list(self.host_queues.items()):
                if queue.empty():
                    continue

                # Check concurrent limit (replaces semaphore check)
                if self.host_active[host] >= self.max_per_host:
                    continue

                # Check time-based politeness
                last = self.last_access.get(host, 0)
                if now - last < self.delay_per_host:
                    continue

                # Acquire work
                url = await queue.get()
                self.host_active[host] += 1
                self.last_access[host] = now
                self._metrics.queue_size.dec()
                return host, url
            return None

    async def release(self, host: str):
        async with self._lock:
            self.host_active[host] -= 1
