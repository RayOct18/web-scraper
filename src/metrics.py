from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Labels: mode (real/simulation), dns_cache (on/off), workers
LABEL_NAMES = ["mode", "dns_cache", "workers"]

_pages_crawled = Counter(
    "crawler_pages_crawled_total",
    "Total pages crawled",
    LABEL_NAMES,
)
_active_requests = Gauge(
    "crawler_active_requests",
    "Active requests",
    LABEL_NAMES,
)
_queue_size = Gauge(
    "crawler_queue_size",
    "Queue size",
    LABEL_NAMES,
)
_request_duration = Histogram(
    "crawler_request_duration_seconds",
    "Request duration",
    LABEL_NAMES,
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

# DNS Cache metrics
_dns_cache_hits = Counter(
    "crawler_dns_cache_hits_total",
    "DNS cache hits",
    LABEL_NAMES,
)
_dns_cache_misses = Counter(
    "crawler_dns_cache_misses_total",
    "DNS cache misses",
    LABEL_NAMES,
)
_dns_cache_size = Gauge(
    "crawler_dns_cache_size",
    "Number of cached DNS entries",
    LABEL_NAMES,
)


class _NullCounter:
    def inc(self, amount=1):
        pass


class _NullGauge:
    def inc(self, amount=1):
        pass

    def dec(self, amount=1):
        pass

    def set(self, value):
        pass


class _NullHistogram:
    def observe(self, amount):
        pass


class NullMetrics:
    """No-op metrics (for url_collector or testing)"""

    def __init__(self):
        self.pages_crawled = _NullCounter()
        self.active_requests = _NullGauge()
        self.queue_size = _NullGauge()
        self.request_duration = _NullHistogram()
        self.dns_cache_hits = _NullCounter()
        self.dns_cache_misses = _NullCounter()
        self.dns_cache_size = _NullGauge()


class Metrics:
    """Prometheus metrics wrapper"""

    def __init__(self, mode: str, dns_cache: bool, workers: int):
        labels = {
            "mode": mode,
            "dns_cache": "on" if dns_cache else "off",
            "workers": str(workers),
        }
        self.pages_crawled = _pages_crawled.labels(**labels)
        self.active_requests = _active_requests.labels(**labels)
        self.queue_size = _queue_size.labels(**labels)
        self.request_duration = _request_duration.labels(**labels)
        self.dns_cache_hits = _dns_cache_hits.labels(**labels)
        self.dns_cache_misses = _dns_cache_misses.labels(**labels)
        self.dns_cache_size = _dns_cache_size.labels(**labels)


def start_metrics_server(port: int):
    start_http_server(port)
