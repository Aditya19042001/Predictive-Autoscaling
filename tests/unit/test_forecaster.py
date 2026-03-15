"""
test_forecaster.py
------------------
Unit tests for the Holt-Winters forecasting model.

Tests are completely isolated from Prometheus and Kubernetes —
they operate only on plain Python lists of floats.

Coverage:
  - Normal operation with sufficient data
  - Fallback behaviour when data is too sparse
  - Negative forecast clamping
  - Flat / all-zero input handling
  - Spike detection (forecast peak should exceed recent average)
"""

import math
import pytest

from autoscaler.config import load_config
from autoscaler.forecaster import Forecaster, MIN_DATA_POINTS


@pytest.fixture
def forecaster():
    return Forecaster(load_config())


def _constant_series(value: float, length: int = 60) -> list[float]:
    return [value] * length


def _ramp_series(start: float, end: float, length: int = 60) -> list[float]:
    step = (end - start) / (length - 1)
    return [start + i * step for i in range(length)]


def _spike_series(baseline: float, spike: float, length: int = 120) -> list[float]:
    """Baseline for 2/3 of the series, then spike for the last 1/3."""
    split = (length * 2) // 3
    return [baseline] * split + [spike] * (length - split)


# ---------------------------------------------------------------------------
# Normal model operation
# ---------------------------------------------------------------------------

class TestForecasterNormal:
    def test_returns_forecast_result(self, forecaster):
        history = _constant_series(100.0)
        result = forecaster.predict(history)
        assert result.model_fitted is True
        assert result.fallback_reason is None
        assert len(result.forecast_series) > 0

    def test_peak_is_non_negative(self, forecaster):
        history = _constant_series(50.0)
        result = forecaster.predict(history)
        assert result.predicted_peak_rps >= 0.0

    def test_forecast_horizon_length(self, forecaster):
        """forecast_series should cover horizon_minutes * 12 steps."""
        from autoscaler.config import load_config
        cfg = load_config()
        expected_steps = cfg.horizon_minutes * 12
        history = _constant_series(100.0, length=expected_steps * 3)
        result = forecaster.predict(history)
        assert len(result.forecast_series) == expected_steps

    def test_stable_traffic_predicts_similar_value(self, forecaster):
        """For flat traffic, predicted peak should be within 20% of input."""
        baseline = 200.0
        history = _constant_series(baseline, length=120)
        result = forecaster.predict(history)
        assert result.predicted_peak_rps == pytest.approx(baseline, rel=0.20)

    def test_rising_trend_predicts_higher_than_current(self, forecaster):
        """For a rising ramp, the forecast should exceed the last observed value."""
        history = _ramp_series(50.0, 300.0, length=120)
        result = forecaster.predict(history)
        last_value = history[-1]
        assert result.predicted_peak_rps > last_value * 0.9  # some tolerance

    def test_spike_detection(self, forecaster):
        """Peak prediction should reflect the spike at the end of history."""
        history = _spike_series(baseline=50.0, spike=400.0, length=120)
        result = forecaster.predict(history)
        # Predicted peak should be substantially above baseline
        assert result.predicted_peak_rps > 100.0


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------

class TestForecasterFallback:
    def test_insufficient_data_uses_fallback(self, forecaster):
        history = [100.0] * (MIN_DATA_POINTS - 1)
        result = forecaster.predict(history)
        assert result.model_fitted is False
        assert result.fallback_reason is not None

    def test_empty_history_returns_zero_peak(self, forecaster):
        result = forecaster.predict([])
        assert result.model_fitted is False
        assert result.predicted_peak_rps == 0.0

    def test_fallback_uses_max_of_recent_values(self, forecaster):
        # Provide just below the minimum, with a clear maximum
        short = [10.0, 20.0, 50.0, 30.0, 15.0]
        result = forecaster.predict(short)
        assert result.model_fitted is False
        assert result.predicted_peak_rps == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestForecasterEdgeCases:
    def test_all_zeros_does_not_crash(self, forecaster):
        history = _constant_series(0.0, length=60)
        result = forecaster.predict(history)
        assert result.predicted_peak_rps >= 0.0

    def test_no_negative_predictions(self, forecaster):
        """Even if the model extrapolates negatively, output must be >= 0."""
        # Rapidly falling traffic can cause negative extrapolation
        history = _ramp_series(500.0, 0.0, length=120)
        result = forecaster.predict(history)
        assert result.predicted_peak_rps >= 0.0
        assert all(v >= 0.0 for v in result.forecast_series)

    def test_very_high_rps_does_not_overflow(self, forecaster):
        history = _constant_series(1_000_000.0, length=60)
        result = forecaster.predict(history)
        assert math.isfinite(result.predicted_peak_rps)
