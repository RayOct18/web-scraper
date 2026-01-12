from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Labels: mode (real/simulation), dns_cache (on/off), workers
LABEL_NAMES = ["mode", "dns_cache", "workers"]

pages_crawled = Counter(
    "crawler_pages_crawled_total",
    "Total pages crawled",
    LABEL_NAMES,
)
active_requests = Gauge(
    "crawler_active_requests",
    "Active requests",
    LABEL_NAMES,
)
queue_size = Gauge(
    "crawler_queue_size",
    "Queue size",
    LABEL_NAMES,
)
request_duration = Histogram(
    "crawler_request_duration_seconds",
    "Request duration",
    LABEL_NAMES,
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

# DNS Cache metrics
dns_cache_hits = Counter(
    "crawler_dns_cache_hits_total",
    "DNS cache hits",
    LABEL_NAMES,
)
dns_cache_misses = Counter(
    "crawler_dns_cache_misses_total",
    "DNS cache misses",
    LABEL_NAMES,
)
dns_cache_size = Gauge(
    "crawler_dns_cache_size",
    "Number of cached DNS entries",
    LABEL_NAMES,
)

# 當前 labels（由 main.py 設定）
_current_labels: dict[str, str] = {}


def set_labels(mode: str, dns_cache: bool, workers: int):
    """設定當前運行的 labels"""
    global _current_labels
    _current_labels = {
        "mode": mode,
        "dns_cache": "on" if dns_cache else "off",
        "workers": str(workers),
    }


def get_labeled_metrics():
    """取得帶有當前 labels 的 metrics"""
    labels = _current_labels
    return (
        pages_crawled.labels(**labels),
        active_requests.labels(**labels),
        queue_size.labels(**labels),
        request_duration.labels(**labels),
    )


def get_dns_metrics():
    """取得帶有當前 labels 的 DNS metrics"""
    labels = _current_labels
    return (
        dns_cache_hits.labels(**labels),
        dns_cache_misses.labels(**labels),
        dns_cache_size.labels(**labels),
    )


def start_metrics_server(port: int):
    start_http_server(port)
