import asyncio
from collections import defaultdict
from urllib.parse import urlparse


class Frontier:
    def __init__(self, max_per_host: int):
        self.max_per_host = max_per_host
        self.seen: set[str] = set()
        self.seen_lock = asyncio.Lock()
        self.host_queues: dict[str, asyncio.Queue[str]] = {}
        self.host_semaphores: dict[str, asyncio.Semaphore] = {}
        self.available_hosts: asyncio.Queue[str] = asyncio.Queue()
        self._host_has_urls: dict[str, bool] = defaultdict(bool)

    def _get_host(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or "unknown"

    async def add(self, url: str) -> bool:
        async with self.seen_lock:
            if url in self.seen:
                return False
            self.seen.add(url)

        host = self._get_host(url)

        if host not in self.host_queues:
            self.host_queues[host] = asyncio.Queue()
            self.host_semaphores[host] = asyncio.Semaphore(self.max_per_host)

        await self.host_queues[host].put(url)

        if not self._host_has_urls[host]:
            self._host_has_urls[host] = True
            await self.available_hosts.put(host)

        return True

    async def get(self) -> tuple[str, str] | None:
        try:
            host = await asyncio.wait_for(self.available_hosts.get(), timeout=0.05)
        except asyncio.TimeoutError:
            return None

        queue = self.host_queues.get(host)
        sem = self.host_semaphores.get(host)

        if not queue or not sem:
            return None

        acquired = sem.locked() is False
        if not acquired:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=0.01)
                acquired = True
            except asyncio.TimeoutError:
                await self.available_hosts.put(host)
                return None

        try:
            url = queue.get_nowait()

            if not queue.empty():
                await self.available_hosts.put(host)
            else:
                self._host_has_urls[host] = False

            return host, url
        except asyncio.QueueEmpty:
            sem.release()
            self._host_has_urls[host] = False
            return None

    def release(self, host: str):
        sem = self.host_semaphores.get(host)
        if sem:
            sem.release()

        if host in self.host_queues and not self.host_queues[host].empty():
            if not self._host_has_urls[host]:
                self._host_has_urls[host] = True
                asyncio.create_task(self.available_hosts.put(host))

    def stats(self) -> tuple[int, int, int]:
        queued = sum(q.qsize() for q in self.host_queues.values())
        active = sum(
            self.max_per_host - sem._value
            for sem in self.host_semaphores.values()
        )
        domains = len(self.host_queues)
        return queued, active, domains
