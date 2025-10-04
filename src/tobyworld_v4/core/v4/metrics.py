# tobyworld_v4/core/v4/metrics.py
"""
Mirror V4 Prometheus metrics (multiprocess-aware).
This module centralizes commonly used counters/histograms/gauges.
Safe to import from multiple processes. If PROMETHEUS_MULTIPROC_DIR is set,
we build a fresh CollectorRegistry and attach a MultiProcessCollector.
Otherwise we fall back to the default REGISTRY.
"""

from __future__ import annotations
import os
import time
from contextlib import contextmanager
from prometheus_client import (
    CollectorRegistry, multiprocess,
    generate_latest, CONTENT_TYPE_LATEST,
    Counter, Histogram, Gauge
)

# Registry (multiprocess-aware if env is set)
if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
    REG = CollectorRegistry()
    multiprocess.MultiProcessCollector(REG)
else:
    from prometheus_client import REGISTRY as REG

# ---- Route-level core metrics ----
mv4_requests_total = Counter(
    "mv4_requests_total",
    "Total HTTP requests by route",
    ["route"], registry=REG
)

mv4_request_latency_seconds = Histogram(
    "mv4_request_latency_seconds",
    "HTTP request latency (s) by route",
    ["route"], registry=REG
)

# In-flight gauge to watch active handlers
mv4_inflight_requests = Gauge(
    "mv4_inflight_requests",
    "In-flight requests by route",
    ["route"], registry=REG
)

# Failures by route (exceptions thrown)
mv4_failures_total = Counter(
    "mv4_failures_total",
    "Failed requests by route",
    ["route"], registry=REG
)

# ---- Extras used by server or tests ----
mv4_llm_fallbacks_total = Counter(
    "mv4_llm_fallbacks_total",
    "LLM fallbacks due to weak/empty output",
    [], registry=REG
)

mv4_reindex_lock_collisions_total = Counter(
    "mv4_reindex_lock_collisions_total",
    "Reindex attempts blocked by lock",
    [], registry=REG
)

def metrics_app(environ, start_response):
    """WSGI adapter for exposing metrics via Starlette/FastAPI mount."""
    data = generate_latest(REG)
    start_response("200 OK", [("Content-Type", CONTENT_TYPE_LATEST)])
    return [data]

# ---- Helper context manager (optional) ----
@contextmanager
def track_request(route: str):
    """
    Wrap a request handler to auto-track inflight, count, latency, failures.

    Example:
        with track_request("ask"):
            ... handler body ...
    """
    mv4_inflight_requests.labels(route=route).inc()
    t0 = time.perf_counter()
    try:
        yield
    except Exception:
        mv4_failures_total.labels(route=route).inc()
        raise
    finally:
        mv4_requests_total.labels(route=route).inc()
        mv4_request_latency_seconds.labels(route=route).observe(time.perf_counter() - t0)
        mv4_inflight_requests.labels(route=route).dec()

__all__ = [
    "REG",
    "generate_latest",
    "CONTENT_TYPE_LATEST",
    "mv4_requests_total",
    "mv4_request_latency_seconds",
    "mv4_inflight_requests",
    "mv4_failures_total",
    "mv4_llm_fallbacks_total",
    "mv4_reindex_lock_collisions_total",
    "metrics_app",
    "track_request",
]
