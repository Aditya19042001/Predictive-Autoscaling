"""
routers/api.py
--------------
All HTTP route handlers for the API service.

Three route groups:
  /api/v1/ping     — lightweight health check, used by load generator for baseline traffic
  /api/v1/process  — CPU-bound endpoint, simulates real workload
  /api/v1/status   — returns current pod identity and replica info (useful during demo)

Middleware pattern:
  Every handler calls _record_request() at the end, which updates all
  Prometheus counters/histograms in one place so the route logic stays clean.
"""

import time
import os
import hashlib
import random
import psutil

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.metrics import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    INFLIGHT_REQUESTS,
    ERROR_COUNT,
    PROCESSED_ITEMS,
    CPU_USAGE_PERCENT,
    MEMORY_USAGE_BYTES,
    ACTIVE_CONNECTIONS,
)

router = APIRouter(prefix="/api/v1")

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    data: str
    item_type: str = "default"
    complexity: int = 1          # 1–10; controls simulated CPU cost


class ProcessResponse(BaseModel):
    status: str
    result: str
    processing_time_ms: float
    pod_name: str


class StatusResponse(BaseModel):
    pod_name: str
    namespace: str
    node_name: str
    cpu_percent: float
    memory_mb: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pod_name() -> str:
    return os.getenv("POD_NAME", "local-dev")


def _record_request(method: str, endpoint: str, status_code: int, duration: float):
    """Update all traffic metrics after a request completes."""
    labels = dict(method=method, endpoint=endpoint, status_code=str(status_code))
    REQUEST_COUNT.labels(**labels).inc()
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)
    if status_code >= 400:
        ERROR_COUNT.labels(**labels).inc()


def _simulate_cpu_work(complexity: int):
    """
    Burn CPU proportional to complexity (1-10).
    Uses repeated SHA-256 hashing — predictable, portable, no external deps.
    At complexity=1  ~0.5 ms;  complexity=10 ~5 ms.
    """
    iterations = complexity * 5_000
    data = b"workload-seed"
    for _ in range(iterations):
        data = hashlib.sha256(data).digest()


def _update_system_gauges():
    """Refresh system-level gauges. Called on every /process request."""
    proc = psutil.Process()
    CPU_USAGE_PERCENT.set(proc.cpu_percent(interval=None))
    MEMORY_USAGE_BYTES.set(proc.memory_info().rss)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/ping")
async def ping(request: Request):
    """
    Lightweight liveness endpoint.
    The load generator hammers this to generate baseline request-rate signal
    for Prometheus without burning significant CPU.
    """
    start = time.perf_counter()
    INFLIGHT_REQUESTS.inc()
    try:
        return {"status": "ok", "pod": _pod_name(), "ts": time.time()}
    finally:
        INFLIGHT_REQUESTS.dec()
        _record_request("GET", "/api/v1/ping", 200, time.perf_counter() - start)


@router.post("/process", response_model=ProcessResponse)
async def process(request: Request, body: ProcessRequest):
    """
    CPU-bound processing endpoint.

    Simulates real application work via SHA-256 hashing whose cost
    scales with body.complexity (1–10). This gives us a controllable
    knob to drive CPU metrics during load tests.

    Also deliberately adds a small random jitter (0–10 ms) so latency
    histograms are interesting rather than flat.
    """
    start = time.perf_counter()
    INFLIGHT_REQUESTS.inc()

    if not 1 <= body.complexity <= 10:
        INFLIGHT_REQUESTS.dec()
        _record_request("POST", "/api/v1/process", 422, time.perf_counter() - start)
        raise HTTPException(status_code=422, detail="complexity must be between 1 and 10")

    try:
        _simulate_cpu_work(body.complexity)
        _update_system_gauges()

        # Random jitter simulates network/DB variance
        jitter = random.uniform(0, 0.010)
        time.sleep(jitter)

        duration = time.perf_counter() - start
        PROCESSED_ITEMS.labels(item_type=body.item_type, status="success").inc()
        _record_request("POST", "/api/v1/process", 200, duration)

        return ProcessResponse(
            status="success",
            result=hashlib.md5(body.data.encode()).hexdigest(),
            processing_time_ms=round(duration * 1000, 2),
            pod_name=_pod_name(),
        )

    except Exception as exc:
        PROCESSED_ITEMS.labels(item_type=body.item_type, status="error").inc()
        _record_request("POST", "/api/v1/process", 500, time.perf_counter() - start)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    finally:
        INFLIGHT_REQUESTS.dec()


@router.get("/status", response_model=StatusResponse)
async def status():
    """
    Returns current pod identity and live system metrics.
    Useful during the demo to confirm which pod is serving and
    to watch memory/CPU shift as the autoscaler adds replicas.
    """
    start = time.perf_counter()
    proc = psutil.Process()

    result = StatusResponse(
        pod_name=_pod_name(),
        namespace=os.getenv("NAMESPACE", "default"),
        node_name=os.getenv("NODE_NAME", "unknown"),
        cpu_percent=proc.cpu_percent(interval=0.1),
        memory_mb=round(proc.memory_info().rss / 1_048_576, 2),
    )

    _record_request("GET", "/api/v1/status", 200, time.perf_counter() - start)
    return result
