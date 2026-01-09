#!/usr/bin/env python3
"""
DNS Cache 效果測試

測試項目：
1. 無 cache — 每次都查 DNS
2. 有 cache — 第一次查完存起來

執行: uv run python benchmark/dns_test.py
"""

import socket
import time
from functools import lru_cache


# 測試用的真實 domain
DOMAINS = [
    "go.dev",
    "github.com",
    "google.com",
    "stackoverflow.com",
    "python.org",
    "rust-lang.org",
    "nodejs.org",
    "docs.docker.com",
    "kubernetes.io",
    "aws.amazon.com",
    "cloud.google.com",
    "azure.microsoft.com",
    "npmjs.com",
    "pypi.org",
    "crates.io",
    "reddit.com",
    "twitter.com",
    "linkedin.com",
    "medium.com",
    "dev.to",
]


def dns_lookup_no_cache(domain: str) -> list[str]:
    """無 cache 的 DNS 查詢"""
    try:
        return socket.gethostbyname_ex(domain)[2]
    except socket.gaierror:
        return []


@lru_cache(maxsize=10000)
def dns_lookup_with_cache(domain: str) -> tuple[str, ...]:
    """有 cache 的 DNS 查詢（使用 lru_cache）"""
    try:
        return tuple(socket.gethostbyname_ex(domain)[2])
    except socket.gaierror:
        return ()


class DNSCache:
    """手動實作的 DNS Cache"""

    def __init__(self):
        self._cache: dict[str, list[str]] = {}
        self._hits = 0
        self._misses = 0

    def lookup(self, domain: str) -> list[str]:
        if domain in self._cache:
            self._hits += 1
            return self._cache[domain]

        self._misses += 1
        try:
            ips = socket.gethostbyname_ex(domain)[2]
            self._cache[domain] = ips
            return ips
        except socket.gaierror:
            self._cache[domain] = []
            return []

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0,
        }


def benchmark_no_cache(domains: list[str], rounds: int) -> float:
    """測試無 cache 的 DNS 查詢"""
    # 清除系統 DNS cache（需要 root，這裡只是重新查詢）
    start = time.perf_counter()
    for _ in range(rounds):
        for domain in domains:
            dns_lookup_no_cache(domain)
    return time.perf_counter() - start


def benchmark_with_cache(domains: list[str], rounds: int) -> float:
    """測試有 cache 的 DNS 查詢"""
    # 清除 lru_cache
    dns_lookup_with_cache.cache_clear()

    start = time.perf_counter()
    for _ in range(rounds):
        for domain in domains:
            dns_lookup_with_cache(domain)
    return time.perf_counter() - start


def benchmark_manual_cache(domains: list[str], rounds: int) -> tuple[float, dict]:
    """測試手動 cache 的 DNS 查詢"""
    cache = DNSCache()

    start = time.perf_counter()
    for _ in range(rounds):
        for domain in domains:
            cache.lookup(domain)
    elapsed = time.perf_counter() - start

    return elapsed, cache.stats


def main():
    rounds = 10
    total_lookups = len(DOMAINS) * rounds

    print("=" * 70)
    print("DNS Cache 效果測試")
    print("=" * 70)
    print(f"測試 {len(DOMAINS)} 個 domain，重複 {rounds} 輪")
    print(f"總共 {total_lookups:,} 次 DNS 查詢")
    print()

    # 預熱（讓系統 DNS cache 有資料）
    print("預熱中...")
    for domain in DOMAINS:
        try:
            socket.gethostbyname(domain)
        except socket.gaierror:
            pass
    print()

    # --- 無 Cache 測試 ---
    print("測試 1: 無 Cache（每次都查詢）")
    no_cache_time = benchmark_no_cache(DOMAINS, rounds)
    print(f"  總時間: {no_cache_time * 1000:.1f} ms")
    print(f"  每次查詢: {no_cache_time / total_lookups * 1000:.3f} ms")
    print()

    # --- lru_cache 測試 ---
    print("測試 2: 使用 @lru_cache")
    with_cache_time = benchmark_with_cache(DOMAINS, rounds)
    cache_info = dns_lookup_with_cache.cache_info()
    print(f"  總時間: {with_cache_time * 1000:.1f} ms")
    print(f"  每次查詢: {with_cache_time / total_lookups * 1000:.3f} ms")
    print(f"  Cache hits: {cache_info.hits}, misses: {cache_info.misses}")
    print()

    # --- 手動 Cache 測試 ---
    print("測試 3: 手動 DNS Cache")
    manual_cache_time, stats = benchmark_manual_cache(DOMAINS, rounds)
    print(f"  總時間: {manual_cache_time * 1000:.1f} ms")
    print(f"  每次查詢: {manual_cache_time / total_lookups * 1000:.3f} ms")
    print(f"  Cache hits: {stats['hits']}, misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1%}")
    print()

    # --- 結果比較 ---
    print("=" * 70)
    print("結果比較")
    print("=" * 70)
    print(f"{'方法':<20} {'總時間':<15} {'每次查詢':<15} {'加速比':<10}")
    print("-" * 70)
    print(f"{'無 Cache':<20} {no_cache_time * 1000:.1f} ms{'':<8} {no_cache_time / total_lookups * 1000:.3f} ms{'':<8} 1.0x")
    print(f"{'@lru_cache':<20} {with_cache_time * 1000:.1f} ms{'':<8} {with_cache_time / total_lookups * 1000:.3f} ms{'':<8} {no_cache_time / with_cache_time:.1f}x")
    print(f"{'手動 Cache':<20} {manual_cache_time * 1000:.1f} ms{'':<8} {manual_cache_time / total_lookups * 1000:.3f} ms{'':<8} {no_cache_time / manual_cache_time:.1f}x")

    # --- 爬蟲場景估算 ---
    print()
    print("=" * 70)
    print("爬蟲場景估算（400 QPS）")
    print("=" * 70)

    avg_no_cache_ms = no_cache_time / total_lookups * 1000
    avg_with_cache_ms = with_cache_time / total_lookups * 1000

    print(f"假設爬 1000 個不同 domain，每個 domain 爬 100 頁")
    print(f"總共 100,000 次 DNS 查詢")
    print()
    print(f"無 Cache: {avg_no_cache_ms:.3f} ms × 100,000 = {avg_no_cache_ms * 100_000 / 1000:.1f} 秒")
    print(f"有 Cache: 1000 次實際查詢 + 99,000 次 cache hit")
    print(f"          {avg_no_cache_ms:.3f} ms × 1,000 + ~0 ms × 99,000 = {avg_no_cache_ms * 1000 / 1000:.1f} 秒")
    print()
    print(f"節省時間: {avg_no_cache_ms * 99_000 / 1000:.1f} 秒")


if __name__ == "__main__":
    main()
