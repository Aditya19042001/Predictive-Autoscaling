"""
forecaster.py
-------------
Time-series forecasting using Holt-Winters exponential smoothing.

Model choice rationale:
  Holt-Winters (triple exponential smoothing) is chosen because:
    - Captures level, trend, AND seasonality — all present in HTTP traffic
    - Trains in milliseconds on 20 minutes of data (240 points at 5s intervals)
    - Deterministic output — no randomness, no GPU, no training instability
    - statsmodels implementation is battle-tested and well-documented
    - Prediction intervals available if confidence-based scaling is added later

Alternatives explicitly rejected:
    - ARIMA:   no seasonality handling without SARIMA; manual order selection
    - Prophet: high latency, heavyweight dependency, overkill for 20-min window
    - LSTM:    requires large datasets, training instability, ops burden

ForecastResult dataclass:
  Carries both the predicted peak and the full forecast series so the
  decision engine can inspect the shape (not just the peak) if needed.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from autoscaler.config import Config

logger = logging.getLogger(__name__)

# Minimum number of data points required to fit the model.
# Below this we fall back to the current value (no prediction).
MIN_DATA_POINTS = 24   # 24 × 5s = 2 minutes of history


@dataclass
class ForecastResult:
    predicted_peak_rps: float
    """Maximum predicted RPS over the forecast horizon. Used for pod sizing."""

    forecast_series: list[float]
    """Full forecast series (one value per 5s step over the horizon)."""

    model_fitted: bool
    """False if we fell back to a simple heuristic (not enough data)."""

    fallback_reason: str | None
    """Human-readable reason if model_fitted=False."""


class Forecaster:
    def __init__(self, config: Config):
        self._horizon_steps = config.horizon_minutes * 12   # 12 steps/min at 5s
        self._seasonal_periods = config.seasonal_periods
        self._min_points = MIN_DATA_POINTS

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def predict(self, history: list[float]) -> ForecastResult:
        """
        Fit a Holt-Winters model to `history` and forecast forward.

        Args:
            history: Per-second RPS values in chronological order.
                     Produced by PrometheusClient.fetch_request_rate().

        Returns:
            ForecastResult with the predicted peak and full series.
        """
        if len(history) < self._min_points:
            return self._fallback(
                history,
                f"Only {len(history)} data points (need >= {self._min_points})",
            )

        series = pd.Series(history, dtype=float)

        # Replace any NaN/Inf that occasionally slip through from Prometheus
        series = series.replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0)

        try:
            forecast_series = self._fit_and_forecast(series)
        except Exception as exc:
            logger.warning("Holt-Winters fit failed (%s), using fallback", exc)
            return self._fallback(history, str(exc))

        # Clamp negative forecasts — RPS can't be negative
        forecast_series = [max(0.0, v) for v in forecast_series]
        peak = max(forecast_series) if forecast_series else 0.0

        logger.info(
            "Forecast: peak=%.1f RPS over next %d steps (horizon=%d min)",
            peak, len(forecast_series), self._horizon_steps // 12,
        )

        return ForecastResult(
            predicted_peak_rps=peak,
            forecast_series=forecast_series,
            model_fitted=True,
            fallback_reason=None,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fit_and_forecast(self, series: pd.Series) -> list[float]:
        """
        Fit Holt-Winters and return forecast values.

        Tries additive seasonality first (appropriate when seasonal amplitude
        is roughly constant). If seasonal_periods > len(series)//2 we drop
        seasonality and use simple double exponential smoothing (trend only).
        """
        n = len(series)
        use_seasonal = (self._seasonal_periods * 2) <= n

        model = ExponentialSmoothing(
            series,
            trend="add",
            seasonal="add" if use_seasonal else None,
            seasonal_periods=self._seasonal_periods if use_seasonal else None,
            initialization_method="estimated",
        )

        fit = model.fit(optimized=True, remove_bias=True)
        forecast = fit.forecast(steps=self._horizon_steps)
        return forecast.tolist()

    def _fallback(self, history: list[float], reason: str) -> ForecastResult:
        """
        Fallback when Holt-Winters cannot be fitted.

        Strategy: use the maximum of the last 5 available values.
        This is conservative — we'd rather over-provision than under-provision.
        """
        logger.warning("Using fallback forecast. Reason: %s", reason)
        recent = history[-5:] if len(history) >= 5 else history
        peak = max(recent) if recent else 0.0
        return ForecastResult(
            predicted_peak_rps=peak,
            forecast_series=[peak] * self._horizon_steps,
            model_fitted=False,
            fallback_reason=reason,
        )
