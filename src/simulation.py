"""
Simulation Module - 模擬測試相關功能

提供：
1. URLPool - 管理預先收集的 URL 池
2. DNSResolver - DNS 解析器（支援可選的 cache）
3. simulated_fetch - 模擬 HTTP 請求（真實 DNS + 模擬延遲）
"""

import json
import random
from pathlib import Path

import aiodns
from cachetools import TTLCache
from src.metrics import Metrics


class DNSResolver:
    """DNS 解析器（使用 aiodns + 可選 TTLCache）"""

    def __init__(
        self,
        use_cache: bool = False,
        cache_size: int = 1024,
        ttl: int = 300,
        *,
        metrics: Metrics,
    ):
        self._resolver = aiodns.DNSResolver()
        self._cache: TTLCache[str, list[str]] | None = None
        self._metrics = metrics

        if use_cache:
            self._cache = TTLCache(maxsize=cache_size, ttl=ttl)

    async def _do_resolve(self, hostname: str) -> list[str]:
        """使用 aiodns 做真正的 DNS 查詢"""
        try:
            result = await self._resolver.query(hostname, "A")
            return [r.host for r in result]
        except aiodns.error.DNSError:
            return []

    async def resolve(self, hostname: str) -> list[str]:
        """非同步解析 hostname 為 IP 地址列表"""
        if self._cache is not None and hostname in self._cache:
            self._metrics.dns_cache_hits.inc()
            return self._cache[hostname]

        self._metrics.dns_cache_misses.inc()

        ips = await self._do_resolve(hostname)

        if self._cache is not None:
            self._cache[hostname] = ips
            self._metrics.dns_cache_size.set(len(self._cache))

        return ips


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
