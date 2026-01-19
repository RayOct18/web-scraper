# Python Web Crawler

高效能網路爬蟲實作，使用 Python asyncio + aiohttp。[筆記連結](https://hackmd.io/@-4tblbsWSwu3rYgE5d0CCw/B1XX0Pir-l)

## 架構

```
┌──────────────────────────────────────────────────────────────┐
│                         Crawler                              │
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                │
│  │ Worker 1 │    │ Worker 2 │    │ Worker N │  (asyncio)     │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘                │
│       │               │               │                      │
│       └───────────────┼───────────────┘                      │
│                       ▼                                      │
│              ┌────────────────┐                              │
│              │    Frontier    │                              │
│              │ ┌────────────┐ │                              │
│              │ │ Per-Host   │ │  ← 每個 domain 獨立 queue    │
│              │ │ Queues +   │ │  ← 計數器控制並發            │
│              │ │ Rate Limit │ │  ← 時間間隔限制              │
│              │ └────────────┘ │                              │
│              └────────────────┘                              │
│                       │                                      │
│              ┌────────────────┐                              │
│              │   Visited Set  │  ← 去重（支援 Bloom Filter） │
│              └────────────────┘                              │
└──────────────────────────────────────────────────────────────┘
```

## 快速開始

### 安裝依賴

```bash
uv sync
```

### 執行爬蟲

```bash
# 真實模式（發送實際 HTTP 請求）
uv run python src/main.py

# 模擬模式（不發送真實請求，用於效能測試）
uv run python src/main.py --simulation --delay-ms 50

# 帶 DNS Cache 的模擬模式
uv run python src/main.py --simulation --dns-cache

# 自訂參數
uv run python src/main.py --workers 50 --max-per-host 5 --max-pages 10000
```

### CLI 參數

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `--max-pages` | 最大爬取頁數 | 30000 |
| `--workers` | Worker 數量 | 20 |
| `--max-per-host` | 每個 domain 最大並發 | 10 |
| `--delay-per-host` | 同一 host 請求間隔（秒） | 0.5 |
| `--simulation` | 啟用模擬模式 | false |
| `--delay-ms` | 模擬延遲（毫秒） | 50 |
| `--url-pool` | URL 池檔案路徑 | url_pool.json |
| `--bloom` | 使用 Bloom Filter 去重 | false |
| `--dns-cache` | 啟用 DNS Cache | false |

### 建立 URL 池（模擬模式用）

```bash
# 先收集真實 URL 建立 URL 池
uv run python src/url_collector.py --max-pages 5000

# 之後可用模擬模式測試
uv run python src/main.py --simulation
```

## 設計重點

### 1. 禮貌性 (Politeness)

- **Per-host queue**：每個 domain 獨立的 URL 佇列
- **並發限制**：計數器限制同一 domain 的並發數（預設 10）
- **時間間隔**：同一 host 請求間隔（預設 0.5 秒）

### 2. 去重 (Deduplication)

- 預設使用 `set` 儲存已訪問 URL
- 支援 **Bloom Filter** 節省記憶體（使用 `--bloom` 啟用）

### 3. 效能優化

| 優化項目 | 效果 |
|---------|------|
| Bloom Filter | 記憶體減少 **88-100x** |
| DNS Cache | 查詢加速 **10-12x** |

### 4. 模擬模式

支援不發送真實 HTTP 請求的模擬模式，用於：
- **效能測試**：測量爬蟲架構本身的極限 QPS
- **DNS Cache 效果驗證**：真實 DNS 查詢 + 模擬下載
- **架構開發**：快速迭代而不影響目標網站

模擬模式流程：
1. 先用 `url_collector.py` 收集真實 URL 建立 URL 池
2. 模擬時從 URL 池隨機選取連結（維持 domain 多樣性）
3. 執行真實 DNS 查詢，但跳過實際下載

### 5. 監控

使用 Docker Compose 啟動 Prometheus + Grafana：

```bash
docker compose up -d
```

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9091
- **Metrics endpoint**: `:9090/metrics`
- 指標：pages_crawled, active_requests, request_duration, queue_size

