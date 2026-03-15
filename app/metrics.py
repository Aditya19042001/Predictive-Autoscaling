"""
metrics.py
----------
All Prometheus metric objects for the API service.

Centralising metrics here means every module imports from one place —
no duplicate registrations, no collision errors from the default registry.

Metric types used:
  Counter   — monotonically increasing value (requests, errors)
  Histogram — distribution of observed values (latency, payload size)
  Gauge     — value that goes up and down (inflight requests, CPU %)
"""

from prometheus_client import Counter, Histogram, Gauge

# ---------------------------------------------------------------------------
# Request traffic
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    name="http_requests_total",
    documentation="Total number of HTTP requests received.",
    labelnames=["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    name="request_latency_seconds",
    documentation="End-to-end HTTP request latency in seconds.",
    labelnames=["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

INFLIGHT_REQUESTS = Gauge(
    name="inflight_requests",
    documentation="Number of HTTP requests currently being processed.",
)

REQUEST_SIZE_BYTES = Histogram(
    name="request_size_bytes",
    documentation="Size of incoming request bodies in bytes.",
    labelnames=["endpoint"],
    buckets=[64, 256, 1_024, 4_096, 16_384, 65_536],
)

# ---------------------------------------------------------------------------
# Error tracking
# ---------------------------------------------------------------------------

ERROR_COUNT = Counter(
    name="http_errors_total",
    documentation="Total number of HTTP errors (4xx and 5xx responses).",
    labelnames=["method", "endpoint", "status_code"],
)

# ---------------------------------------------------------------------------
# System / workload simulation
# ---------------------------------------------------------------------------

CPU_USAGE_PERCENT = Gauge(
    name="cpu_usage_percent",
    documentation="Simulated CPU utilisation percentage (0-100).",
)

MEMORY_USAGE_BYTES = Gauge(
    name="memory_usage_bytes",
    documentation="Current process RSS memory in bytes.",
)

ACTIVE_CONNECTIONS = Gauge(
    name="active_connections",
    documentation="Number of currently open client connections.",
)

# ---------------------------------------------------------------------------
# Business / domain metrics (demonstrate multi-dimensional labelling)
# ---------------------------------------------------------------------------

PROCESSED_ITEMS = Counter(
    name="processed_items_total",
    documentation="Total items processed by the /process endpoint.",
    labelnames=["item_type", "status"],
)
