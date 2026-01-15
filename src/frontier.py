import asyncio
from urllib.parse import urlparse


class Frontier:
    """URL 管理 - 負責 dedup、per-host queues、rate limiting"""

    def __init__(self, max_per_host: int):
        self.max_per_host = max_per_host

        # URL deduplication
        self.seen: set[str] = set()
        self.seen_lock = asyncio.Lock()

        # Per-host queues and rate limiting
        self.host_queues: dict[str, asyncio.Queue[str]] = {}
        self.host_semaphores: dict[str, asyncio.Semaphore] = {}
        self.host_active: dict[str, int] = {}  # 追蹤每個 host 的活躍數

        # Round-robin state
        self._last_host_index = 0

    def _get_host(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or "unknown"

    async def add(self, url: str) -> bool:
        """Add a URL to the frontier."""
        async with self.seen_lock:
            if url in self.seen:
                return False
            self.seen.add(url)

        host = self._get_host(url)

        if host not in self.host_queues:
            self.host_queues[host] = asyncio.Queue()
            self.host_semaphores[host] = asyncio.Semaphore(self.max_per_host)
            self.host_active[host] = 0

        await self.host_queues[host].put(url)
        return True

    def release(self, host: str):
        """Release a host's semaphore after work is done."""
        sem = self.host_semaphores.get(host)
        if sem:
            sem.release()
            self.host_active[host] = max(0, self.host_active.get(host, 0) - 1)

    async def get_work(self) -> tuple[str, str] | None:
        """Get available work using round-robin."""
        hosts = list(self.host_queues.keys())
        n = len(hosts)

        if n == 0:
            return None

        for i in range(n):
            idx = (self._last_host_index + i) % n
            host = hosts[idx]

            queue = self.host_queues.get(host)
            sem = self.host_semaphores.get(host)

            if not queue or not sem or queue.empty():
                continue

            # Check rate limit (non-blocking)
            if self.host_active.get(host, 0) >= self.max_per_host:
                continue

            await sem.acquire()
            self.host_active[host] = self.host_active.get(host, 0) + 1
            self._last_host_index = (idx + 1) % n

            try:
                url = queue.get_nowait()
                return host, url
            except asyncio.QueueEmpty:
                sem.release()
                self.host_active[host] -= 1
                continue

        return None

    def stats(self) -> tuple[int, int, int]:
        queued = sum(q.qsize() for q in self.host_queues.values())
        active = sum(self.host_active.values())
        domains = len(self.host_queues)
        return queued, active, domains
