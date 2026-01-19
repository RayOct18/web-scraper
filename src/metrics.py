from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

# Labels: mode (real/simulation), dns_cache (on/off), workers
LABEL_NAMES = ["mode", "dns_cache", "workers"]


class Metrics:
    """Prometheus metrics wrapper.

    Use default REGISTRY for production (metrics scrapable on port 9090).
    Use empty CollectorRegistry() for url_collector (metrics work but not collected).
    """

    def __init__(
        self,
        mode: str,
        dns_cache: bool,
        workers: int,
        registry: CollectorRegistry = REGISTRY,
    ):
        labels = {
            "mode": mode,
            "dns_cache": "on" if dns_cache else "off",
            "workers": str(workers),
        }

        # Create metrics on the provided registry
        pages_crawled = Counter(
            "crawler_pages_crawled_total",
            "Total pages crawled",
            LABEL_NAMES,
            registry=registry,
        )
        active_requests = Gauge(
            "crawler_active_requests",
            "Active requests",
            LABEL_NAMES,
            registry=registry,
        )
        queue_size = Gauge(
            "crawler_queue_size",
            "Queue size",
            LABEL_NAMES,
            registry=registry,
        )
        request_duration = Histogram(
            "crawler_request_duration_seconds",
            "Request duration",
            LABEL_NAMES,
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
            registry=registry,
        )
        dns_cache_hits = Counter(
            "crawler_dns_cache_hits_total",
            "DNS cache hits",
            LABEL_NAMES,
            registry=registry,
        )
        dns_cache_misses = Counter(
            "crawler_dns_cache_misses_total",
            "DNS cache misses",
            LABEL_NAMES,
            registry=registry,
        )
        dns_cache_size = Gauge(
            "crawler_dns_cache_size",
            "Number of cached DNS entries",
            LABEL_NAMES,
            registry=registry,
        )
        fetch_success = Counter(
            "crawler_fetch_success_total",
            "Total successful fetches",
            LABEL_NAMES,
            registry=registry,
        )
        fetch_failure = Counter(
            "crawler_fetch_failure_total",
            "Total failed fetches",
            LABEL_NAMES,
            registry=registry,
        )

        # Apply labels
        self.pages_crawled = pages_crawled.labels(**labels)
        self.active_requests = active_requests.labels(**labels)
        self.queue_size = queue_size.labels(**labels)
        self.request_duration = request_duration.labels(**labels)
        self.dns_cache_hits = dns_cache_hits.labels(**labels)
        self.dns_cache_misses = dns_cache_misses.labels(**labels)
        self.dns_cache_size = dns_cache_size.labels(**labels)
        self.fetch_success = fetch_success.labels(**labels)
        self.fetch_failure = fetch_failure.labels(**labels)


def start_metrics_server(port: int):
    start_http_server(port)
