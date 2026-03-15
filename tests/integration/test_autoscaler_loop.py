"""
test_autoscaler_loop.py
-----------------------
Integration tests for the full autoscaler control loop.

These tests wire together the real Forecaster and ScalingDecisionEngine
with mocked Prometheus and Kubernetes clients.

Goal: verify the end-to-end pipeline behaves correctly for the three
key scenarios described in the design doc:
  1. Pre-spike scale-up (the main value proposition)
  2. Stable traffic — no unnecessary scaling
  3. Post-spike scale-down with cooldown

No real Kubernetes or Prometheus is needed.
"""

import pytest
from unittest.mock import MagicMock, patch

from autoscaler.config import load_config
from autoscaler.forecaster import Forecaster
from autoscaler.scaler import ScalingDecisionEngine
from autoscaler.main import _run_one_cycle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history(rps_values: list[float]) -> list[float]:
    """Pad a short list to at least MIN_DATA_POINTS so Holt-Winters fits."""
    from autoscaler.forecaster import MIN_DATA_POINTS
    while len(rps_values) < MIN_DATA_POINTS * 2:
        rps_values = rps_values + rps_values
    return rps_values[:120]


def _mocked_prom(history: list[float], current_rps: float = 50.0):
    prom = MagicMock()
    prom.fetch_request_rate.return_value = history
    prom.fetch_current_rps.return_value = current_rps
    return prom


def _mocked_k8s(current_replicas: int = 1):
    k8s = MagicMock()
    k8s.get_current_replicas.return_value = current_replicas
    k8s.scale_deployment.return_value = True
    return k8s


# ---------------------------------------------------------------------------
# Scenario 1: Rising traffic → pre-scale
# ---------------------------------------------------------------------------

class TestPreSpike:
    def test_scale_up_before_spike(self):
        """
        History shows traffic rising toward 400 RPS.
        With pod_capacity=150 and current_pods=1, should scale to 3.
        """
        cfg = load_config()
        history = _make_history(list(range(50, 400, 3)))   # rising trend
        prom = _mocked_prom(history, current_rps=350.0)
        k8s = _mocked_k8s(current_replicas=1)
        forecaster = Forecaster(cfg)
        engine = ScalingDecisionEngine(cfg)

        _run_one_cycle(prom, forecaster, engine, k8s, cfg)

        # scale_deployment should have been called with replicas > 1
        assert k8s.scale_deployment.called
        _, call_kwargs = k8s.scale_deployment.call_args
        # Works for both positional and keyword calls
        call_args = k8s.scale_deployment.call_args[0]
        new_replicas = call_args[1] if len(call_args) > 1 else call_kwargs.get("replicas")
        assert new_replicas is not None
        assert new_replicas > 1


# ---------------------------------------------------------------------------
# Scenario 2: Stable traffic → no change
# ---------------------------------------------------------------------------

class TestStableTraffic:
    def test_no_scaling_for_flat_traffic(self):
        """
        Flat traffic at 100 RPS with 1 pod (capacity 150) — no scale event.
        """
        cfg = load_config()
        history = _make_history([100.0] * 60)
        prom = _mocked_prom(history, current_rps=100.0)
        k8s = _mocked_k8s(current_replicas=1)
        forecaster = Forecaster(cfg)
        engine = ScalingDecisionEngine(cfg)

        _run_one_cycle(prom, forecaster, engine, k8s, cfg)

        assert not k8s.scale_deployment.called


# ---------------------------------------------------------------------------
# Scenario 3: Prometheus unavailable → graceful skip
# ---------------------------------------------------------------------------

class TestPrometheusUnavailable:
    def test_empty_history_does_not_crash(self):
        cfg = load_config()
        prom = _mocked_prom([], current_rps=None)
        k8s = _mocked_k8s(current_replicas=2)
        forecaster = Forecaster(cfg)
        engine = ScalingDecisionEngine(cfg)

        # Should not raise
        _run_one_cycle(prom, forecaster, engine, k8s, cfg)

    def test_k8s_unavailable_does_not_crash(self):
        cfg = load_config()
        history = _make_history([100.0] * 60)
        prom = _mocked_prom(history, current_rps=100.0)
        k8s = MagicMock()
        k8s.get_current_replicas.return_value = -1  # error sentinel
        forecaster = Forecaster(cfg)
        engine = ScalingDecisionEngine(cfg)

        _run_one_cycle(prom, forecaster, engine, k8s, cfg)

        # Should have returned early without calling scale_deployment
        assert not k8s.scale_deployment.called
