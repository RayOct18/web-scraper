"""
Fetcher Module - HTTP 請求抽象

提供 HttpFetcher 類別，封裝 aiohttp session 和 timeout。
"""

from __future__ import annotations

import time

import aiohttp


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
