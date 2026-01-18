"""
Fetcher Module - HTTP 請求抽象

提供 HttpFetcher 類別，封裝 aiohttp session 和 timeout。
"""

from __future__ import annotations

import time

import aiohttp
import asyncio
from urllib.parse import urlparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.simulation import DNSResolver


class HttpFetcher:
    """HTTP fetcher，管理 session 生命週期。

    Usage:
        async with HttpFetcher(timeout=10.0) as fetcher:
            status, body, duration, error = await fetcher.fetch(url)
    """

    def __init__(self, timeout: float = 10.0):
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> HttpFetcher:
        connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
        self._session = aiohttp.ClientSession(connector=connector)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch(self, url: str) -> tuple[int, str, float, str | None]:
        """Fetch URL，回傳 (status, body, duration, error)。"""
        if not self._session:
            raise RuntimeError("HttpFetcher must be used as async context manager")

        start = time.monotonic()
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=self._timeout)
            ) as resp:
                body = await resp.text()
                return resp.status, body, time.monotonic() - start, None
        except Exception as e:
            return 0, "", time.monotonic() - start, str(e)


class SimulatedFetcher:
    """模擬 fetcher，執行真實 DNS 查詢但以固定延遲模擬下載。

    Usage:
        fetcher = SimulatedFetcher(delay_ms=50, dns_resolver=resolver)
        status, body, duration, error = await fetcher.fetch(url)
    """

    def __init__(self, delay_ms: int, dns_resolver: DNSResolver | None = None):
        self._delay_ms = delay_ms
        self._dns_resolver = dns_resolver

    async def __aenter__(self) -> SimulatedFetcher:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def fetch(
        self,
        url: str,
    ) -> tuple[int, str, float, str | None]:
        """
        模擬 HTTP 請求：
        1. 做真實的 DNS 查詢（如果提供 resolver）
        2. 用固定延遲模擬下載時間（不真正下載）

        回傳格式與真實 fetch 相同：
        (status, body, duration, error)
        """
        start = time.monotonic()

        try:
            # 1. DNS 查詢（真實，非阻塞）
            if self._dns_resolver:
                hostname = urlparse(url).netloc
                await self._dns_resolver.resolve(hostname)

            # 2. 模擬延遲（不真正下載）
            delay_sec = self._delay_ms / 1000
            await asyncio.sleep(delay_sec)

            # 回傳真實總時間（DNS + 模擬延遲）
            total_duration = time.monotonic() - start
            return 200, "", total_duration, None
        except Exception as e:
            return 0, "", time.monotonic() - start, str(e)
