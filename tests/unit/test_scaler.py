"""
test_scaler.py
--------------
Unit tests for the scaling decision engine.

The engine is pure logic (no I/O), so tests are fast and deterministic.
time.monotonic() is patched where cooldown timing needs controlling.

Coverage:
  - Scale-up fires immediately
  - Scale-down threshold gating
  - Scale-down cooldown enforcement
  - min_pods / max_pods bounds
  - No-op when already at the right count
  - Reason string is always populated
"""

import time
import pytest
from unittest.mock import patch

from autoscaler.config import Config
from autoscaler.scaler import ScalingDecisionEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_engine(
    pod_capacity_rps=100.0,
    min_pods=1,
    max_pods=10,
    scale_down_threshold=0.6,
    cooldown_seconds=600,
) -> ScalingDecisionEngine:
    cfg = Config(
        prometheus_url="http://localhost:9090",
        prometheus_timeout_seconds=10,
        target_deployment="api-service",
        namespace="default",
        pod_capacity_rps=pod_capacity_rps,
        min_pods=min_pods,
        max_pods=max_pods,
        lookback_minutes=20,
        horizon_minutes=10,
        seasonal_periods=12,
        loop_interval_seconds=60,
        scale_down_threshold=scale_down_threshold,
        cooldown_seconds=cooldown_seconds,
    )
    return ScalingDecisionEngine(cfg)


# ---------------------------------------------------------------------------
# Scale-up tests
# ---------------------------------------------------------------------------

class TestScaleUp:
    def test_scale_up_when_predicted_exceeds_capacity(self):
        engine = _make_engine(pod_capacity_rps=100.0)
        decision = engine.decide(predicted_rps=250.0, current_pods=1)
        assert decision.should_scale is True
        assert decision.target_pods == 3   # ceil(250/100)

    def test_scale_up_is_immediate_no_cooldown(self):
        engine = _make_engine(pod_capacity_rps=100.0, cooldown_seconds=9999)
        # Simulate a recent scale-down (would block scale-DOWN)
        engine._last_scale_down_at = time.monotonic()
        decision = engine.decide(predicted_rps=500.0, current_pods=1)
        assert decision.should_scale is True
        assert decision.target_pods == 5

    def test_scale_up_reason_mentions_direction(self):
        engine = _make_engine()
        decision = engine.decide(predicted_rps=300.0, current_pods=1)
        assert "UP" in decision.reason or "up" in decision.reason.lower()


# ---------------------------------------------------------------------------
# Scale-down tests
# ---------------------------------------------------------------------------

class TestScaleDown:
    def test_no_scale_down_above_threshold(self):
        engine = _make_engine(pod_capacity_rps=100.0, scale_down_threshold=0.6)
        # 4 pods → 400 RPS capacity; 250 RPS = 62.5% utilisation → above 60%
        decision = engine.decide(predicted_rps=250.0, current_pods=4)
        assert decision.should_scale is False
        assert decision.target_pods == 4

    def test_scale_down_blocked_by_cooldown(self):
        engine = _make_engine(pod_capacity_rps=100.0, cooldown_seconds=600)
        engine._last_scale_down_at = time.monotonic()   # just scaled down
        decision = engine.decide(predicted_rps=50.0, current_pods=4)
        assert decision.should_scale is False
        assert "cooldown" in decision.reason.lower()

    def test_scale_down_allowed_after_cooldown(self):
        engine = _make_engine(pod_capacity_rps=100.0, cooldown_seconds=60)
        # Pretend last scale-down was 120 seconds ago
        engine._last_scale_down_at = time.monotonic() - 120
        decision = engine.decide(predicted_rps=30.0, current_pods=4)
        assert decision.should_scale is True
        assert decision.target_pods < 4

    def test_first_scale_down_no_cooldown_block(self):
        engine = _make_engine(pod_capacity_rps=100.0)
        # No previous scale-down → cooldown is irrelevant
        decision = engine.decide(predicted_rps=20.0, current_pods=4)
        assert decision.should_scale is True


# ---------------------------------------------------------------------------
# Bounds tests
# ---------------------------------------------------------------------------

class TestBounds:
    def test_never_scales_below_min_pods(self):
        engine = _make_engine(pod_capacity_rps=100.0, min_pods=2)
        # Even with 0 RPS predicted, should not go below 2
        decision = engine.decide(predicted_rps=0.0, current_pods=5)
        if decision.should_scale:
            assert decision.target_pods >= 2

    def test_never_scales_above_max_pods(self):
        engine = _make_engine(pod_capacity_rps=100.0, max_pods=5)
        decision = engine.decide(predicted_rps=100_000.0, current_pods=1)
        assert decision.target_pods <= 5

    def test_min_equals_max_means_no_scaling(self):
        engine = _make_engine(pod_capacity_rps=100.0, min_pods=3, max_pods=3)
        decision = engine.decide(predicted_rps=1000.0, current_pods=3)
        assert decision.target_pods == 3


# ---------------------------------------------------------------------------
# No-change tests
# ---------------------------------------------------------------------------

class TestNoChange:
    def test_already_at_right_count(self):
        engine = _make_engine(pod_capacity_rps=100.0)
        # 2 pods, 150 RPS → needs ceil(150/100)=2 pods → no change
        decision = engine.decide(predicted_rps=150.0, current_pods=2)
        assert decision.should_scale is False
        assert decision.target_pods == 2

    def test_reason_always_populated(self):
        engine = _make_engine()
        for rps, pods in [(0, 1), (100, 1), (500, 5), (999, 5)]:
            decision = engine.decide(rps, pods)
            assert decision.reason, f"Empty reason for rps={rps}, pods={pods}"
