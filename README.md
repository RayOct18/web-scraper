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
web-scraper/
├── src/
│   ├── __init__.py       # Package 初始化
│   ├── main.py           # 主程式入口
│   ├── dispatcher.py     # Worker 協調：管理 worker pool 和工作分配
│   ├── frontier.py       # URL 邊境：Per-host queue + semaphore
│   ├── parser.py         # HTML 解析：提取連結
│   ├── config.py         # 設定檔
│   ├── metrics.py        # Prometheus metrics
│   ├── simulation.py     # 模擬模組：URLPool, DNSResolver
│   └── url_collector.py  # URL 收集器：建立模擬用 URL 池
├── grafana/              # Grafana 監控設定
├── prometheus.yml        # Prometheus 設定
├── docker-compose.yml    # 監控服務容器設定
└── pyproject.toml
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
| `--simulation` | 啟用模擬模式 | false |
| `--delay-ms` | 模擬延遲（毫秒） | 50 |
| `--url-pool` | URL 池檔案路徑 | url_pool.json |
| `--bloom` | 使用 Bloom Filter 去重 | false |
| `--dns-cache` | 啟用 DNS Cache | false |

### 建立 URL 池（模擬模式用）

```bash
# 先收集真實 URL 建立 URL 池
uv run python src/url_collector.py --max-pages 50000

# 之後可用模擬模式測試
uv run python src/main.py --simulation
```

## 設計重點

### 1. 禮貌性 (Politeness)

- **Per-host queue**：每個 domain 獨立的 URL 佇列
- **Semaphore**：限制同一 domain 的並發數（預設 10）
- 避免對同一網站發送過多請求

### 2. 去重 (Deduplication)

- 目前使用 `set` 儲存已訪問 URL
- 可升級為 **Bloom Filter** 節省記憶體（見 benchmark）

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

編輯 `src/config.py`：

```python
@dataclass
class Config:
    seed_urls: list[str]              # 種子 URL 列表（預設 50+ 個網站）
    num_workers: int = 20             # Worker 數量
    max_per_host: int = 10            # 每個 domain 最大並發
    max_pages: int = 30000            # 最大爬取頁數
    request_timeout: float = 10.0     # 請求超時（秒）
    metrics_port: int = 9090          # Prometheus metrics port

    # 模擬模式設定
    simulation_mode: bool = False     # 是否啟用模擬模式
    simulation_delay_ms: int = 50     # 模擬延遲（毫秒）
    simulation_links_min: int = 5     # 每頁最少連結數
    simulation_links_max: int = 20    # 每頁最多連結數
    url_pool_file: str = "url_pool.json"

    # 優化選項
    use_bloom_filter: bool = False    # 使用 Bloom Filter 去重
    use_dns_cache: bool = False       # 啟用 DNS Cache
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

## License

MIT
