# 網路爬蟲設計討論記錄

這份文件記錄了從零開始設計高效能爬蟲的完整過程，包含設計決策、效能分析、以及各種優化的實測結果。

---

## 目錄

1. [專案背景](#專案背景)
2. [設計演進](#設計演進)
3. [效能分析](#效能分析)
4. [優化實驗](#優化實驗)
5. [深入理解：Worker、Bloom Filter、DNS Cache 的關係](#深入理解worker-bloom-filter-dns-cache-的關係)
6. [待驗證實驗：優化效果量化](#待驗證實驗優化效果量化)
7. [讀書會 Demo 規劃](#讀書會-demo-規劃)

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

## 深入理解：Worker、Bloom Filter、DNS Cache 的關係

### 問題

> 如果頻寬夠大，只要把 worker 開超大，就可以達到 400 QPS？

### Worker 開太多的影響

理論上 Worker 越多 → 並發越高 → QPS 越高。

**但實際上有上限**：

| 問題 | 症狀 | 原因 |
|------|------|------|
| **頻寬飽和** | p50 延遲飆高、timeout 增加 | 1000 個 request 同時搶 100Mbps |
| **CPU 過載** | 整體變慢 | context switch、HTML parsing 排隊 |
| **記憶體爆炸** | OOM | 每個 request 都在等 response，buffer 堆積 |
| **連線數限制** | connection refused | 超過 ulimit 或 TCP 狀態表 |
| **目標網站限流** | 429 Too Many Requests | 被 ban |

**實測驗證**：
```
30 workers  → 17.5 QPS, p50 正常 ✅
200 workers → p50 = 10 秒 ❌ (timeout)
```

200 workers 時，每個 request 都在排隊等頻寬，延遲飆高。

### Bloom Filter / DNS Cache 如何幫助吞吐量？

**關鍵理解**：它們不是增加並發，而是 **減少浪費**。

#### 爬蟲的時間花在哪？

```
總時間 = DNS 查詢 + TCP 連線 + 下載 + 解析 + 去重檢查
```

| 階段 | 沒優化 | 有優化 | 節省 |
|------|--------|--------|------|
| DNS 查詢 | 20ms/次 | 0ms (cache hit) | **20ms** |
| 去重檢查 | 0.001ms | 0.001ms | 0 |
| 記憶體 | 100MB (1M URLs) | 1MB (Bloom) | **99MB** |

#### DNS Cache 的真正價值

```
沒有 DNS Cache：
  Worker 1: DNS(go.dev) → 20ms → 下載 → ...
  Worker 2: DNS(go.dev) → 20ms → 下載 → ...  ← 重複！
  Worker 3: DNS(go.dev) → 20ms → 下載 → ...  ← 重複！

有 DNS Cache：
  Worker 1: DNS(go.dev) → 20ms → cache 存起來
  Worker 2: cache hit → 0ms → 下載 → ...
  Worker 3: cache hit → 0ms → 下載 → ...
```

**效果**：每個 domain 只查一次 DNS，後續都是 0ms。

#### Bloom Filter 的真正價值

**不是速度，是記憶體**。

| 場景 | Set | Bloom Filter |
|------|-----|--------------|
| 1 億 URL | **6.4 GB** | **120 MB** |
| 10 億 URL | **64 GB** | **1.2 GB** |

當你爬到 1 億頁時：
- Set：需要 64GB RAM，可能要換更大的機器
- Bloom：1.2GB，普通機器就夠

**間接幫助吞吐量**：不用換機器、不用分散式、不會 OOM crash。

### 三者的關係

| 優化 | 作用 | 何時有效 |
|------|------|---------|
| 增加 Worker | 提高並發 | 頻寬未飽和時 |
| DNS Cache | 減少每個 request 的延遲 | 多 domain 爬取 |
| Bloom Filter | 讓你能爬更多頁而不 OOM | 大規模爬取（>100 萬 URL）|

**它們是互補的，不是互斥的。**

### 正確的擴展順序

```
1. 先確認頻寬夠（計算理論上限）
2. 增加 worker 直到 CPU 或記憶體滿
3. 加 DNS Cache（減少每個 request 的延遲）
4. 加 Bloom Filter（讓記憶體撐得住更多 URL）
5. 如果還不夠 → 多台機器 / 分散式
```

---

## 待驗證實驗：優化效果量化

### 實驗目的

在頻寬固定的情況下，量化 DNS Cache 和 Bloom Filter 對吞吐量和資源使用的影響。

### 控制變數

| 固定 | 變動 |
|------|------|
| 頻寬（~90 Mbps） | DNS Cache 開/關 |
| Workers（30） | Bloom Filter 開/關 |
| MaxPerHost（3） | |
| MaxPages（5000） | |

### 測量指標

| 指標 | 意義 |
|------|------|
| 總時間 | 爬完 N 頁花多久 |
| QPS | 吞吐量 |
| 記憶體峰值 | Bloom Filter 效果 |
| DNS 查詢次數 | DNS Cache 效果 |

### 實驗矩陣

| # | DNS Cache | Bloom Filter | 預期效果 |
|---|-----------|--------------|---------|
| 1 | ❌ | ❌ | Baseline |
| 2 | ✅ | ❌ | 延遲降低 → QPS 略升 |
| 3 | ❌ | ✅ | 記憶體降低（QPS 不變）|
| 4 | ✅ | ✅ | 兩者都有 |

### 預期結果

#### DNS Cache

```
Baseline:  每個 request 多 ~20ms DNS
有 Cache:  只有第一次查，後續 0ms

假設爬 5000 頁、500 個 domain：
- 無 Cache: 5000 × 20ms = 100 秒花在 DNS
- 有 Cache: 500 × 20ms = 10 秒花在 DNS
- 節省: 90 秒
```

**注意**：如果頻寬是瓶頸，這 90 秒可能被「等頻寬」蓋過去，改善不明顯。

#### Bloom Filter

```
QPS 不會變，但記憶體會大幅降低。

5000 URLs:
- Set: ~6 MB
- Bloom: ~60 KB

效果在長時間爬取時才明顯（爬幾百頁看不出來）。
```

### 執行方式

```bash
# Baseline
uv run python main.py  # 記錄時間、記憶體

# + DNS Cache
uv run python main.py --dns-cache  # 記錄時間、記憶體

# + Bloom Filter
uv run python main.py --bloom  # 記錄時間、記憶體

# Both
uv run python main.py --dns-cache --bloom
```

### 狀態

⏳ **待實作**：需要將 DNS Cache 和 Bloom Filter 加到 main.py 做成可開關的功能。

---

## 結論

1. **架構設計**比暴力增加 worker 更重要
2. **頻寬是硬限制**，程式優化無法突破
3. **Bloom Filter** 省記憶體，**DNS Cache** 省延遲
4. 測試前先算理論上限，避免走冤枉路
5. **三種優化互補**：Worker 提高並發、DNS Cache 減少延遲、Bloom Filter 減少記憶體

---

## 專案位置

- Go 版：`/home/rayxie/go-scraper/`
- Python 版：`/home/rayxie/python-scraper/`
- 監控：`go-scraper/docker-compose.yml`（Prometheus + Grafana）
