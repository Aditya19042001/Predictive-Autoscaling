"""
main.py
-------
Autoscaler entry point and control loop.

The control loop is intentionally simple and synchronous:
  sleep → wake → fetch → forecast → decide → act → repeat

Why synchronous?
  The loop runs once per minute. All I/O calls (Prometheus, Kubernetes) have
  short timeouts. Async complexity buys nothing here and makes error handling
  and logging harder to follow.

Loop steps:
  1. Fetch last 20 min of request-rate data from Prometheus
  2. Fit Holt-Winters and forecast peak RPS over next 10 min
  3. Compute target pod count (with scale-down guards)
  4. If target != current → PATCH the Kubernetes deployment
  5. Log a structured summary line for every iteration

Observability self-metrics:
  The autoscaler exposes its own /metrics on port 9091 so Prometheus
  can also scrape the predictor's view of the world (predicted RPS,
  target pods, loop errors). This makes the "predicted vs actual" Grafana
  panel possible.
"""

import logging
import sys
import time

from prometheus_client import Gauge, Counter, start_http_server

from autoscaler.config import load_config
from autoscaler.prometheus_client import PrometheusClient
from autoscaler.forecaster import Forecaster
from autoscaler.scaler import ScalingDecisionEngine
from autoscaler.k8s_client import KubernetesClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("autoscaler")

# ---------------------------------------------------------------------------
# Self-metrics (scraped by Prometheus from port 9091)
# ---------------------------------------------------------------------------

PREDICTED_RPS = Gauge(
    "autoscaler_predicted_rps",
    "Forecasted peak requests-per-second for the next horizon window.",
)

CURRENT_PODS = Gauge(
    "autoscaler_current_pods",
    "Current replica count of the managed deployment.",
)

TARGET_PODS = Gauge(
    "autoscaler_target_pods",
    "Target replica count computed by the autoscaler this cycle.",
)

LOOP_ERRORS = Counter(
    "autoscaler_loop_errors_total",
    "Total number of control loop iterations that encountered an error.",
)

SCALE_EVENTS = Counter(
    "autoscaler_scale_events_total",
    "Total scaling actions executed.",
    ["direction"],   # "up" | "down"
)


# ---------------------------------------------------------------------------
# Control loop
# ---------------------------------------------------------------------------

def run_loop(
    prom: PrometheusClient,
    forecaster: Forecaster,
    engine: ScalingDecisionEngine,
    k8s: KubernetesClient,
    cfg,
):
    """Single blocking control loop. Runs until the process is killed."""
    logger.info(
        "Autoscaler started — target=%s/%s, interval=%ds",
        cfg.namespace, cfg.target_deployment, cfg.loop_interval_seconds,
    )

    # Pre-flight: make sure the target deployment exists before looping
    if not k8s.deployment_exists(cfg.target_deployment):
        logger.critical(
            "Target deployment '%s' not found in namespace '%s'. Exiting.",
            cfg.target_deployment, cfg.namespace,
        )
        sys.exit(1)

    while True:
        iteration_start = time.monotonic()

        try:
            _run_one_cycle(prom, forecaster, engine, k8s, cfg)
        except Exception as exc:
            # Catch-all so a transient error never kills the loop
            logger.exception("Unhandled error in control loop iteration: %s", exc)
            LOOP_ERRORS.inc()

        # Sleep for the remainder of the interval (accounting for work time)
        elapsed = time.monotonic() - iteration_start
        sleep_for = max(0.0, cfg.loop_interval_seconds - elapsed)
        logger.debug("Cycle complete in %.2fs, sleeping %.1fs", elapsed, sleep_for)
        time.sleep(sleep_for)


def _run_one_cycle(prom, forecaster, engine, k8s, cfg):
    """Execute one fetch → forecast → decide → act cycle."""

    # Step 1 — fetch metrics
    history = prom.fetch_request_rate()
    current_rps = prom.fetch_current_rps()
    logger.info("Fetched %d data points (current RPS: %s)", len(history),
                f"{current_rps:.1f}" if current_rps is not None else "unknown")

    # Step 2 — forecast
    result = forecaster.predict(history)
    PREDICTED_RPS.set(result.predicted_peak_rps)

    if not result.model_fitted:
        logger.warning("Forecast used fallback heuristic: %s", result.fallback_reason)

    # Step 3 — current state
    current_pods = k8s.get_current_replicas(cfg.target_deployment)
    if current_pods < 0:
        logger.warning("Could not read current replica count — skipping cycle")
        return
    CURRENT_PODS.set(current_pods)

    # Step 4 — decide
    decision = engine.decide(result.predicted_peak_rps, current_pods)
    TARGET_PODS.set(decision.target_pods)

    logger.info(
        "Decision: %s | predicted=%.1f RPS | current=%d pods | target=%d pods",
        "SCALE" if decision.should_scale else "HOLD",
        result.predicted_peak_rps,
        current_pods,
        decision.target_pods,
    )
    logger.info("Reason: %s", decision.reason)

    # Step 5 — act
    if decision.should_scale:
        direction = "up" if decision.target_pods > current_pods else "down"
        success = k8s.scale_deployment(cfg.target_deployment, decision.target_pods)
        if success:
            SCALE_EVENTS.labels(direction=direction).inc()
        else:
            LOOP_ERRORS.inc()
            logger.error("Scale action failed for %s", cfg.target_deployment)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()

    # Start self-metrics HTTP server in a background thread
    # Prometheus will scrape this on port 9091
    start_http_server(port=9091)
    logger.info("Self-metrics server started on :9091/metrics")

    prom       = PrometheusClient(cfg)
    forecaster = Forecaster(cfg)
    engine     = ScalingDecisionEngine(cfg)
    k8s        = KubernetesClient(cfg)

    run_loop(prom, forecaster, engine, k8s, cfg)


if __name__ == "__main__":
    main()
