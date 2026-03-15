"""
config.py
---------
Single source of truth for all autoscaler configuration.

All values are read from environment variables with sensible defaults so
the service runs locally (minikube) without any extra setup, but is also
fully configurable in production by changing the Kubernetes Deployment env block.

Design principle: no magic numbers anywhere else in the codebase.
Every threshold, URL, and interval lives here and is documented.
"""

import os
from dataclasses import dataclass


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


@dataclass(frozen=True)
class Config:
    # ------------------------------------------------------------------
    # Prometheus
    # ------------------------------------------------------------------
    prometheus_url: str
    """Base URL of the Prometheus server. No trailing slash."""

    prometheus_timeout_seconds: int
    """HTTP timeout for PromQL queries."""

    # ------------------------------------------------------------------
    # Target deployment
    # ------------------------------------------------------------------
    target_deployment: str
    """Name of the Kubernetes Deployment this autoscaler manages."""

    namespace: str
    """Kubernetes namespace of the target deployment."""

    # ------------------------------------------------------------------
    # Capacity model
    # ------------------------------------------------------------------
    pod_capacity_rps: float
    """
    Maximum requests-per-second a single healthy pod can sustain.
    Tune this from load testing (e.g. k6 ramp test to find saturation point).
    """

    min_pods: int
    """Floor: never scale below this many replicas."""

    max_pods: int
    """Ceiling: never exceed this many replicas (cluster resource guard)."""

    # ------------------------------------------------------------------
    # Forecasting
    # ------------------------------------------------------------------
    lookback_minutes: int
    """
    How many minutes of historical RPS to feed into Holt-Winters.
    Longer windows = more stable forecasts; shorter = more responsive.
    20 minutes is a good balance for minute-granularity traffic patterns.
    """

    horizon_minutes: int
    """
    How far ahead to forecast.
    10 minutes gives enough lead time for pod startup (typically 60–90 s)
    while not forecasting so far out that accuracy degrades.
    """

    seasonal_periods: int
    """
    Number of observations per season for Holt-Winters.
    With 5s scrape interval and 1-minute seasonality: 60/5 = 12.
    """

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------
    loop_interval_seconds: int
    """How often the autoscaler wakes up and runs the forecast+scale cycle."""

    # ------------------------------------------------------------------
    # Scale-down guard
    # ------------------------------------------------------------------
    scale_down_threshold: float
    """
    Scale down only when predicted_rps < current_capacity * this value.
    0.6 = scale down when utilisation forecast drops below 60% of current capacity.
    Prevents thrashing around the boundary.
    """

    cooldown_seconds: int
    """
    Minimum seconds between two consecutive scale-down actions.
    Scale-up ignores this cooldown — always scale up immediately.
    """


def load_config() -> Config:
    """Build a Config instance from environment variables."""
    return Config(
        prometheus_url=_env("PROMETHEUS_URL", "http://localhost:9090"),
        prometheus_timeout_seconds=_env_int("PROMETHEUS_TIMEOUT_SECONDS", 10),
        target_deployment=_env("TARGET_DEPLOYMENT", "api-service"),
        namespace=_env("NAMESPACE", "default"),
        pod_capacity_rps=_env_float("POD_CAPACITY_RPS", 150.0),
        min_pods=_env_int("MIN_PODS", 1),
        max_pods=_env_int("MAX_PODS", 20),
        lookback_minutes=_env_int("LOOKBACK_MINUTES", 20),
        horizon_minutes=_env_int("HORIZON_MINUTES", 10),
        seasonal_periods=_env_int("SEASONAL_PERIODS", 12),
        loop_interval_seconds=_env_int("LOOP_INTERVAL_SECONDS", 60),
        scale_down_threshold=_env_float("SCALE_DOWN_THRESHOLD", 0.6),
        cooldown_seconds=_env_int("COOLDOWN_SECONDS", 600),
    )
