# 網路爬蟲設計討論記錄

這份文件記錄了從零開始設計高效能爬蟲的完整過程，包含設計決策、效能分析、以及各種優化的實測結果。

---

## 目錄

1. [專案背景](#專案背景)
2. [設計演進](#設計演進)
3. [效能分析](#效能分析)
4. [優化實驗](#優化實驗)
5. [讀書會 Demo 規劃](#讀書會-demo-規劃)

---

## 專案背景

### 起因

原本使用 Python + Scrapy 建立爬蟲，但遇到框架複雜度問題：
- Middleware 模型讓 metrics 追蹤困難
- 難以理解內部運作機制

**決定**：從零開始學習爬蟲設計，先用 Go 完成完整爬蟲，再建立 Python asyncio 版本做比較。

### 目標

達到 **400 QPS**（每秒爬取 400 頁）

這個數字來自經典的系統設計估算：
- 每月 10 億個網頁
- 10億 / 30天 / 24小時 / 3600秒 = **~400 QPS**

---

## 設計演進

### Naive 版本的問題

最簡單的爬蟲（10 行）：

```python
def crawl(url):
    html = requests.get(url).text
    for link in BeautifulSoup(html).find_all('a'):
        crawl(link['href'])  # 遞迴
```

**問題**：
1. ❌ 不禮貌 — 瘋狂打同一個 host
2. ❌ 無限迴圈 — 沒有 visited set
3. ❌ 太慢 — 同步一個一個爬
4. ❌ 記憶體爆炸 — 遞迴太深

### 解決方案

| 問題 | 解決方案 | 實作 |
|------|---------|------|
| 不禮貌 | Per-host queue + semaphore | `frontier.py` |
| 無限迴圈 | Visited set | `set()` |
| 太慢 | Worker pool + 併發 | asyncio workers |
| 記憶體爆炸 | BFS 改用 queue | `asyncio.Queue` |

### Frontier 設計

核心是 **Per-host queue + semaphore**：

```
┌─────────────────────────────────────────┐
│               Frontier                   │
│                                          │
│  host: go.dev                            │
│  ├── queue: [/doc, /blog, /learn]       │
│  └── semaphore: 3 (max concurrent)      │
│                                          │
│  host: github.com                        │
│  ├── queue: [/features, /pricing]       │
│  └── semaphore: 3                       │
│                                          │
│  host: python.org                        │
│  ├── queue: [/downloads]                │
│  └── semaphore: 3                       │
└─────────────────────────────────────────┘
```

**優點**：
- 每個 domain 獨立管理，互不影響
- Semaphore 確保不會對同一網站發送過多請求
- Worker 拿到 URL 就能直接用，不需要再等 limiter

---

## 效能分析

### 實測結果（Go 版本）

| 設定 | 結果 |
|------|------|
| 30 workers, MaxPerHost=3 | 500 頁 / 28 秒 ≈ **17.5 QPS** ✅ |
| 200 workers | p50 延遲 10 秒，大量 timeout ❌ |

### 瓶頸診斷

拉高到 200 workers 時效能反而下降，開始診斷：

```bash
# 檢查系統限制
ulimit -n          # 1,048,576 — 足夠
ss -s              # 33 connections — 沒問題

# 檢查頻寬
curl -o /dev/null -w "Speed: %{speed_download}\n" \
  "https://speed.cloudflare.com/__down?bytes=100000000"
# Speed: 11,185,256 bytes/sec ≈ 90 Mbps
```

**結論**：瓶頸是 **網路頻寬**，不是程式。

### 頻寬與 QPS 的關係

關鍵公式：
```
最大 QPS = 頻寬(bytes/sec) / 平均頁面大小(bytes)
```

| 頻寬 | 50KB 頁面 | 100KB 頁面 |
|------|-----------|------------|
| 90 Mbps (本機) | 180 QPS | 90 QPS |
| 160 Mbps | 320 QPS | 160 QPS |
| 320 Mbps | 640 QPS | 320 QPS |

**結論**：要達到 400 QPS（50KB 頁面），需要約 **160 Mbps** 頻寬。

### 雲端環境測試

| 環境 | 頻寬 | 50KB QPS 上限 |
|------|------|---------------|
| 本機 | 90 Mbps | 180 QPS |
| Oracle Cloud VM | 50 Mbps | 100 QPS |
| AWS t3.medium (預期) | 最高 5 Gbps | 12,500 QPS |

Oracle 免費 VM 比本機還慢！

---

## 優化實驗

### Bloom Filter vs Set

**目的**：減少記憶體使用

**原理**：
- Set 儲存完整 URL 字串
- Bloom Filter 只儲存 hash，但有 false positive

**實測結果**：

| 規模 | Set 記憶體 | Bloom 記憶體 | 節省 |
|------|-----------|-------------|------|
| 10K URLs | 1.2 MB | 11.8 KB | **101x** |
| 100K URLs | 10.8 MB | 117 KB | **94x** |
| 1M URLs | 100.6 MB | 1.1 MB | **88x** |

**意外發現**：Python Set 的 lookup 比 Bloom Filter 快！

| 操作 | Set | Bloom |
|------|-----|-------|
| 1000 次查詢 | 0.23 ms | 6.64 ms |

這是因為 Python 的 dict/set 用 C 實作。Bloom Filter 的優勢是 **記憶體**，不是速度。

**False Positive 測試**：
- 設定 1% error rate
- 實測 10,000 個不存在的 URL
- False Positives: 120 (1.20%) — 符合預期

### DNS Cache

**目的**：減少 DNS 查詢延遲

**背景**（來自讀書會筆記）：
> DNS 會是爬蟲的瓶頸。系統緩存通常只有幾千條（nscd 或 systemd-resolved）。
> 爬蟲可能打出上千上萬的 DNS 查詢，需要自己建 cache。

**實測結果**：

| 方法 | 每次查詢 | 加速比 |
|------|---------|--------|
| 無 Cache | 20.6 ms | 1x |
| @lru_cache | 1.7 ms | **12x** |
| 手動 Cache | 2.1 ms | **10x** |

**爬蟲場景估算**：
- 爬 1000 個 domain，每個 domain 100 頁
- 總共 100,000 次 DNS 查詢

| 方法 | DNS 總時間 |
|------|-----------|
| 無 Cache | 2060 秒（34 分鐘）|
| 有 Cache | 20 秒 |

**節省 34 分鐘！**

### 優化總結

| 優化項目 | 效果 | 適用場景 |
|---------|------|---------|
| Bloom Filter | 記憶體減少 88-100x | URL 數量大（>100 萬）|
| DNS Cache | 延遲減少 10-12x | 多 domain 爬取 |

---

## 讀書會 Demo 規劃

### 主題

**從 0 到 400 QPS — 網路爬蟲的設計與實作**

### 結構（20-30 分鐘）

| 階段 | 時間 | 內容 |
|------|------|------|
| 1. 為什麼需要設計 | 3 min | 展示 naive.py 的問題 |
| 2. 核心問題解決 | 10 min | 逐步加入設計，跑 Grafana 看效果 |
| 3. 效能瓶頸分析 | 5 min | 頻寬計算、雲端比較 |
| 4. 進階優化 | 5 min | Bloom Filter + DNS Cache benchmark |
| 5. 規模估算 | 2 min | 回扣筆記的數字 |

### Demo 指令

```bash
cd /home/rayxie/python-scraper

# 1. 展示 naive 爬蟲的問題（會卡住/爆掉）
uv run python naive.py

# 2. 跑正式爬蟲（搭配 Grafana）
uv run python main.py

# 3. Bloom Filter benchmark
uv run python benchmark/bloom_test.py

# 4. DNS Cache benchmark
uv run python benchmark/dns_test.py
```

### 關鍵數字（回扣讀書會筆記）

| 需求 | 數字 | 對應設計 |
|------|------|---------|
| 每月 10 億頁 | 400 QPS | Worker pool |
| 峰值 800 QPS | 2x buffer | 頻寬 320 Mbps |
| 儲存 5 年 | 30 PB | 內容儲存系統 |
| 30% 重複 | - | Bloom Filter |
| DNS 瓶頸 | 上萬查詢 | DNS Cache |

---

## 結論

1. **架構設計**比暴力增加 worker 更重要
2. **頻寬是硬限制**，程式優化無法突破
3. **Bloom Filter** 省記憶體，**DNS Cache** 省延遲
4. 測試前先算理論上限，避免走冤枉路

---

## 專案位置

- Go 版：`/home/rayxie/go-scraper/`
- Python 版：`/home/rayxie/python-scraper/`
- 監控：`go-scraper/docker-compose.yml`（Prometheus + Grafana）
