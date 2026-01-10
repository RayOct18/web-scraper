"""
Simulation Module - 模擬測試相關功能

提供：
1. URLPool - 管理預先收集的 URL 池
2. DNSResolver - DNS 解析器（支援可選的 cache）
3. simulated_fetch - 模擬 HTTP 請求（真實 DNS + 模擬延遲）
"""

import asyncio
import json
import random
import socket
from pathlib import Path
from urllib.parse import urlparse


class DNSResolver:
    """DNS 解析器（支援可選的 cache）"""

    def __init__(self, use_cache: bool = False):
        self.use_cache = use_cache
        self._cache: dict[str, list[str]] = {}
        self.hits = 0
        self.misses = 0

    def _blocking_resolve(self, hostname: str) -> list[str]:
        """同步 DNS 查詢（會阻塞）"""
        try:
            return socket.gethostbyname_ex(hostname)[2]
        except socket.gaierror:
            return []

    async def resolve(self, hostname: str) -> list[str]:
        """非同步解析 hostname 為 IP 地址列表"""
        if self.use_cache and hostname in self._cache:
            self.hits += 1
            return self._cache[hostname]

        self.misses += 1
        # 使用線程池避免阻塞 event loop
        ips = await asyncio.to_thread(self._blocking_resolve, hostname)

        if self.use_cache:
            self._cache[hostname] = ips
        return ips

    @property
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": self.hits / total if total > 0 else 0,
            "cache_size": len(self._cache),
        }


class URLPool:
    """管理預先收集的 URL 池"""

    def __init__(self, file_path: str):
        self.urls_by_host: dict[str, list[str]] = {}
        self.all_hosts: list[str] = []
        self.total: int = 0
        self._load(file_path)

    def _load(self, file_path: str):
        """從 JSON 檔案載入 URL 池"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(
                f"URL pool file not found: {file_path}\n"
                f"Please run url_collector.py first to generate it:\n"
                f"  uv run python url_collector.py --max-pages 50000"
            )

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.urls_by_host = data.get("urls_by_host", {})
        self.all_hosts = list(self.urls_by_host.keys())
        self.total = data.get("total", 0)

        if not self.all_hosts:
            raise ValueError(f"URL pool is empty: {file_path}")

        print(f"Loaded URL pool: {self.total} URLs from {len(self.all_hosts)} hosts")

    def get_random_links(self, count: int) -> list[str]:
        """
        隨機取得 N 個 URL（維持 domain 多樣性）

        策略：
        1. 先隨機選 host
        2. 再從該 host 的路徑中隨機選一個
        3. 組合成完整 URL

        這樣可以確保連結有 domain 多樣性，
        而不是全部來自同一個 host。
        """
        links = []
        for _ in range(count):
            # 隨機選一個 host
            host = random.choice(self.all_hosts)
            paths = self.urls_by_host[host]

            if paths:
                # 隨機選一個路徑
                path = random.choice(paths)
                # 組合成完整 URL（假設都是 https）
                url = f"https://{host}{path}"
                links.append(url)

        return links

    def get_random_links_from_host(self, host: str, count: int) -> list[str]:
        """從指定 host 隨機取得 N 個 URL"""
        paths = self.urls_by_host.get(host, [])
        if not paths:
            return []

        selected = random.sample(paths, min(count, len(paths)))
        return [f"https://{host}{path}" for path in selected]


async def simulated_fetch(
    url: str,
    delay_ms: int,
    dns_resolver: DNSResolver | None = None,
) -> tuple[int, str, float, str | None]:
    """
    模擬 HTTP 請求：
    1. 做真實的 DNS 查詢（如果提供 resolver）
    2. 用固定延遲模擬下載時間（不真正下載）

    回傳格式與真實 fetch 相同：
    (status, body, duration, error)
    """
    # 1. DNS 查詢（真實，非阻塞）
    if dns_resolver:
        hostname = urlparse(url).netloc
        await dns_resolver.resolve(hostname)

    # 2. 模擬延遲（不真正下載）
    delay_sec = delay_ms / 1000
    await asyncio.sleep(delay_sec)

    return 200, "", delay_sec, None
