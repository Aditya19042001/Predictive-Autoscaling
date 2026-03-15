# Forecasting Model Reference

## Holt-Winters Exponential Smoothing

Also called Triple Exponential Smoothing. Models three components:
  - Level     (α): the baseline value
  - Trend     (β): the rate of change
  - Seasonal  (γ): repeating periodic pattern

### Additive vs Multiplicative Seasonality

This project uses ADDITIVE seasonality:
  observation = level + trend + seasonal_component + noise

Multiplicative would be:
  observation = level × trend × seasonal_component × noise

Additive is correct when the seasonal amplitude is roughly constant
(absolute number of extra requests per cycle stays similar).
Multiplicative is better when amplitude grows proportionally to the level.
For most HTTP traffic at this timescale, additive is appropriate.

### What Happens When Seasonal Periods > Data Length / 2?

The model silently degrades to Double Exponential Smoothing (trend only,
no seasonality). This is handled in forecaster.py:

  use_seasonal = (seasonal_periods * 2) <= len(series)

At seasonal_periods=12, this means seasonality is used once we have
24+ data points (2 minutes of history at 5s scrape interval).

### Prediction Intervals (Future Enhancement)

statsmodels ExponentialSmoothing fit results expose:
  fit.simulate(nsimulations, repetitions, error, random_errors)

This can generate prediction intervals. A future enhancement could use
the upper bound of the 90% prediction interval for scaling decisions
(conservative) vs the point forecast (neutral) depending on cost constraints.

## Fallback Strategy

When the model cannot be fitted (< 24 data points, or numerical failure):
  predicted_rps = max(history[-5:])

This is deliberately conservative — we use the recent peak rather than
the mean. Under-provisioning is always worse than a brief over-provision.
