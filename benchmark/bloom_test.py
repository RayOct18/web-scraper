#!/usr/bin/env python3
"""
Bloom Filter vs Set 效能比較

測試項目：
1. 記憶體使用量
2. 插入速度
3. 查詢速度

執行: uv run python benchmark/bloom_test.py
"""

import sys
import time
from typing import Callable

# 需要安裝: uv add pybloom-live
try:
    from pybloom_live import BloomFilter
except ImportError:
    print("請先安裝: uv add pybloom-live")
    sys.exit(1)


def get_size(obj) -> int:
    """估算物件記憶體大小（bytes）"""
    if isinstance(obj, set):
        # set 的大小 + 所有字串的大小
        return sys.getsizeof(obj) + sum(sys.getsizeof(s) for s in obj)
    elif isinstance(obj, BloomFilter):
        # Bloom filter 的 bit array 大小
        return sys.getsizeof(obj.bitarray)
    return sys.getsizeof(obj)


def format_size(bytes_size: int) -> str:
    """格式化大小"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    else:
        return f"{bytes_size / (1024 * 1024):.1f} MB"


def generate_urls(n: int) -> list[str]:
    """產生測試用 URL"""
    return [f"https://example.com/page/{i}" for i in range(n)]


def benchmark_insert(name: str, container, urls: list[str], add_func: Callable) -> float:
    """測試插入速度"""
    start = time.perf_counter()
    for url in urls:
        add_func(container, url)
    elapsed = time.perf_counter() - start
    return elapsed


def benchmark_lookup(name: str, container, urls: list[str], check_func: Callable) -> float:
    """測試查詢速度"""
    start = time.perf_counter()
    for url in urls:
        check_func(container, url)
    elapsed = time.perf_counter() - start
    return elapsed


def main():
    # 測試規模
    sizes = [10_000, 100_000, 1_000_000]

    print("=" * 70)
    print("Bloom Filter vs Python Set 效能比較")
    print("=" * 70)

    for n in sizes:
        print(f"\n{'─' * 70}")
        print(f"測試規模: {n:,} URLs")
        print(f"{'─' * 70}")

        urls = generate_urls(n)
        lookup_urls = urls[:1000]  # 只測 1000 次查詢

        # --- Python Set ---
        py_set: set[str] = set()
        set_insert_time = benchmark_insert(
            "Set", py_set, urls, lambda s, u: s.add(u)
        )
        set_lookup_time = benchmark_lookup(
            "Set", py_set, lookup_urls, lambda s, u: u in s
        )
        set_size = get_size(py_set)

        # --- Bloom Filter ---
        # 1% false positive rate
        bloom = BloomFilter(capacity=n, error_rate=0.01)
        bloom_insert_time = benchmark_insert(
            "Bloom", bloom, urls, lambda b, u: b.add(u)
        )
        bloom_lookup_time = benchmark_lookup(
            "Bloom", bloom, lookup_urls, lambda b, u: u in b
        )
        bloom_size = get_size(bloom)

        # --- 結果 ---
        print(f"\n{'項目':<15} {'Python Set':<20} {'Bloom Filter':<20} {'差異':<15}")
        print("-" * 70)

        print(f"{'記憶體':<15} {format_size(set_size):<20} {format_size(bloom_size):<20} {set_size / bloom_size:.1f}x 節省")
        print(f"{'插入時間':<15} {set_insert_time * 1000:.1f} ms{'':<13} {bloom_insert_time * 1000:.1f} ms")
        print(f"{'查詢時間':<15} {set_lookup_time * 1000:.2f} ms{'':<12} {bloom_lookup_time * 1000:.2f} ms")
        print(f"{'每秒插入':<15} {n / set_insert_time:,.0f} ops{'':<12} {n / bloom_insert_time:,.0f} ops")

        # 清理
        del py_set, bloom, urls

    # False Positive 測試
    print(f"\n{'=' * 70}")
    print("False Positive 測試")
    print("=" * 70)

    bloom = BloomFilter(capacity=100_000, error_rate=0.01)
    for i in range(100_000):
        bloom.add(f"https://example.com/page/{i}")

    # 測試不存在的 URL
    false_positives = 0
    test_count = 10_000
    for i in range(100_000, 100_000 + test_count):
        if f"https://example.com/page/{i}" in bloom:
            false_positives += 1

    print(f"測試 {test_count:,} 個不存在的 URL")
    print(f"False Positives: {false_positives} ({false_positives / test_count * 100:.2f}%)")
    print(f"預期: ~1%")


if __name__ == "__main__":
    main()
