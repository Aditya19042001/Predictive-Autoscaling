"""
main.py
-------
FastAPI application entry point.

Responsibilities:
  1. Create the FastAPI app instance
  2. Register startup/shutdown lifecycle hooks
     - startup:  initialise system-gauge background thread
     - shutdown: flush final metrics
  3. Mount the Prometheus /metrics endpoint (via prometheus_client's ASGI handler)
  4. Include the API router
  5. Add request-level middleware for ACTIVE_CONNECTIONS gauge

Running locally:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Running in Docker / Kubernetes:
  CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

import threading
import time

import psutil
from fastapi import FastAPI, Request
from prometheus_client import make_asgi_app

from app.routers import api
from app.metrics import (
    CPU_USAGE_PERCENT,
    MEMORY_USAGE_BYTES,
    ACTIVE_CONNECTIONS,
)

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Predictive Autoscaler — Demo API",
    description=(
        "A FastAPI service instrumented with Prometheus metrics. "
        "Deployed in Kubernetes and managed by the predictive autoscaler."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Mount Prometheus metrics endpoint
# Prometheus scrapes GET /metrics on this path every 5 seconds.
# make_asgi_app() returns a standards-compliant ASGI app that serialises
# all registered metric objects into the Prometheus text format.
# ---------------------------------------------------------------------------

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

app.include_router(api.router)

# ---------------------------------------------------------------------------
# Background system-gauge updater
# Runs in a daemon thread; updates CPU and memory gauges every 5 seconds
# independently of request traffic so the gauges stay fresh during idle periods.
# ---------------------------------------------------------------------------

_stop_event = threading.Event()


def _system_gauge_loop():
    proc = psutil.Process()
    while not _stop_event.is_set():
        try:
            CPU_USAGE_PERCENT.set(proc.cpu_percent(interval=1.0))
            MEMORY_USAGE_BYTES.set(proc.memory_info().rss)
        except Exception:
            pass   # never crash the background thread
        time.sleep(4)


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    t = threading.Thread(target=_system_gauge_loop, daemon=True)
    t.start()


@app.on_event("shutdown")
def on_shutdown():
    _stop_event.set()


# ---------------------------------------------------------------------------
# Middleware — active connection tracking
# ---------------------------------------------------------------------------

@app.middleware("http")
async def track_connections(request: Request, call_next):
    ACTIVE_CONNECTIONS.inc()
    try:
        response = await call_next(request)
        return response
    finally:
        ACTIVE_CONNECTIONS.dec()


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    return {"service": "api-service", "docs": "/docs", "metrics": "/metrics"}
