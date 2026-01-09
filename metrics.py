from prometheus_client import Counter, Gauge, Histogram, start_http_server

pages_crawled = Counter("crawler_pages_crawled_total", "Total pages crawled")
active_requests = Gauge("crawler_active_requests", "Active requests")
queue_size = Gauge("crawler_queue_size", "Queue size")
request_duration = Histogram(
    "crawler_request_duration_seconds",
    "Request duration",
    buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)


def start_metrics_server(port: int):
    start_http_server(port)
