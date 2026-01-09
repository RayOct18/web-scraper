# Python Web Crawler

高效能網路爬蟲實作，使用 Python asyncio + aiohttp。

## 專案目標

從零開始學習爬蟲設計，目標達到 **400 QPS**（每秒 400 頁）。

## 架構

```
┌─────────────────────────────────────────────────────────────┐
│                         Crawler                              │
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐               │
│  │ Worker 1 │    │ Worker 2 │    │ Worker N │  (asyncio)    │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘               │
│       │               │               │                      │
│       └───────────────┼───────────────┘                      │
│                       ▼                                      │
│              ┌────────────────┐                              │
│              │    Frontier    │                              │
│              │ ┌────────────┐ │                              │
│              │ │ Per-Host   │ │  ← 每個 domain 獨立 queue    │
│              │ │ Queues +   │ │  ← Semaphore 控制並發        │
│              │ │ Semaphores │ │                              │
│              │ └────────────┘ │                              │
│              └────────────────┘                              │
│                       │                                      │
│              ┌────────────────┐                              │
│              │   Visited Set  │  ← 去重（未來可換 Bloom）     │
│              └────────────────┘                              │
└─────────────────────────────────────────────────────────────┘
```

## 檔案結構

```
python-scraper/
├── main.py              # 主程式：Worker pool + graceful shutdown
├── frontier.py          # URL 邊境：Per-host queue + semaphore
├── parser.py            # HTML 解析：提取連結
├── config.py            # 設定檔
├── metrics.py           # Prometheus metrics
├── naive.py             # 展示問題的 naive 爬蟲
├── benchmark/
│   ├── bloom_test.py    # Bloom Filter vs Set 效能測試
│   └── dns_test.py      # DNS Cache 效果測試
└── pyproject.toml
```

## 快速開始

### 安裝依賴

```bash
uv sync
```

### 執行爬蟲

```bash
uv run python main.py
```

### 執行 Benchmark

```bash
# Bloom Filter vs Set
uv run python benchmark/bloom_test.py

# DNS Cache 效果
uv run python benchmark/dns_test.py
```

## 設計重點

### 1. 禮貌性 (Politeness)

- **Per-host queue**：每個 domain 獨立的 URL 佇列
- **Semaphore**：限制同一 domain 的並發數（預設 3）
- 避免對同一網站發送過多請求

### 2. 去重 (Deduplication)

- 目前使用 `set` 儲存已訪問 URL
- 可升級為 **Bloom Filter** 節省記憶體（見 benchmark）

### 3. 效能優化

| 優化項目 | 效果 |
|---------|------|
| Bloom Filter | 記憶體減少 **88-100x** |
| DNS Cache | 查詢加速 **10-12x** |

### 4. 監控

- Prometheus metrics 在 `:8000/metrics`
- 指標：pages_crawled, active_requests, request_duration, queue_size

## Benchmark 結果

### Bloom Filter vs Set

| 規模 | Set 記憶體 | Bloom 記憶體 | 節省 |
|------|-----------|-------------|------|
| 10K URLs | 1.2 MB | 11.8 KB | 101x |
| 100K URLs | 10.8 MB | 117 KB | 94x |
| 1M URLs | 100.6 MB | 1.1 MB | 88x |

### DNS Cache

| 方法 | 每次查詢 | 加速比 |
|------|---------|--------|
| 無 Cache | 20.6 ms | 1x |
| @lru_cache | 1.7 ms | 12x |

## 設定

編輯 `config.py`：

```python
@dataclass
class Config:
    num_workers: int = 30           # Worker 數量
    max_per_host: int = 3           # 每個 domain 最大並發
    max_pages: int = 500            # 最大爬取頁數
    request_timeout: float = 10.0   # 請求超時（秒）
```

## QPS 與頻寬關係

| 頻寬 | 平均頁面 50KB | 平均頁面 100KB |
|------|--------------|----------------|
| 100 Mbps | 250 QPS | 125 QPS |
| 200 Mbps | 500 QPS | 250 QPS |
| 1 Gbps | 2500 QPS | 1250 QPS |

要達到 400 QPS（50KB 頁面），需要約 **160 Mbps** 頻寬。

## 相關專案

- Go 版本：`/home/rayxie/go-scraper/`
- 監控：Prometheus + Grafana（見 go-scraper/docker-compose.yml）

## License

MIT
