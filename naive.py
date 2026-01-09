#!/usr/bin/env python3
"""
Naive 爬蟲 — 展示問題用

問題：
1. 不禮貌 — 瘋狂打同一個 host
2. 無限迴圈 — 沒有 visited set
3. 太慢 — 同步一個一個爬
4. 記憶體爆炸 — 遞迴太深
5. 沒有錯誤處理
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def crawl(url: str, depth: int = 0) -> None:
    """遞迴爬取網頁"""
    print(f"{'  ' * depth}Crawling: {url}")

    html = requests.get(url, timeout=10).text
    soup = BeautifulSoup(html, "html.parser")

    for link in soup.find_all("a", href=True):
        next_url = urljoin(url, link["href"])
        if next_url.startswith("http"):
            crawl(next_url, depth + 1)  # 遞迴！問題在這


if __name__ == "__main__":
    # 跑幾秒就會看到問題
    crawl("https://go.dev/")
