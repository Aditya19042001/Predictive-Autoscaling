"""
prometheus_client.py
--------------------
Thin wrapper around Prometheus's HTTP API (PromQL query_range endpoint).

Responsibilities:
  - Build the correct PromQL expression for request-rate time-series
  - Execute the range query with a configurable lookback window
  - Parse the JSON response into a plain Python list of floats
  - Handle connectivity errors and empty results gracefully

Why a custom client instead of the official prometheus-api-client library?
  The official library is heavier than needed here. We only ever run one
  specific query (rate over a range). A 50-line focused client is easier
  to test, mock, and reason about.

PromQL used:
  rate(http_requests_total[1m])
  — gives per-second request rate averaged over 1-minute windows.
  Scrape interval is 5s so each step returns one data point per 5 seconds.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from autoscaler.config import Config

logger = logging.getLogger(__name__)


class PrometheusQueryError(Exception):
    """Raised when the Prometheus API returns an error or unexpected shape."""


class PrometheusClient:
    def __init__(self, config: Config):
        self._base_url = config.prometheus_url.rstrip("/")
        self._timeout = config.prometheus_timeout_seconds
        self._lookback_minutes = config.lookback_minutes

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_request_rate(self) -> list[float]:
        """
        Query Prometheus for the per-second HTTP request rate over the
        last `lookback_minutes` minutes.

        Returns a list of floats (one per scrape interval, chronological).
        Returns an empty list if Prometheus is unreachable or has no data.

        The caller (forecaster) is responsible for deciding what to do
        with an empty list — this method never raises on empty data.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=self._lookback_minutes)

        try:
            raw = self._query_range(
                query='rate(http_requests_total[1m])',
                start=start,
                end=end,
                step="5s",
            )
            values = self._parse_matrix(raw)
            logger.debug("Fetched %d data points from Prometheus", len(values))
            return values

        except PrometheusQueryError as exc:
            logger.warning("Prometheus query failed: %s", exc)
            return []
        except requests.RequestException as exc:
            logger.warning("Prometheus unreachable: %s", exc)
            return []

    def fetch_current_rps(self) -> Optional[float]:
        """
        Instant query: current request rate (averaged over last 1 minute).
        Used for logging/observability, not for forecasting.
        Returns None if unavailable.
        """
        try:
            resp = requests.get(
                f"{self._base_url}/api/v1/query",
                params={"query": "sum(rate(http_requests_total[1m]))"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return None
            return float(results[0]["value"][1])
        except Exception as exc:
            logger.warning("Could not fetch current RPS: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str,
    ) -> dict:
        """Execute a PromQL range query and return the raw JSON data block."""
        params = {
            "query": query,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": step,
        }
        resp = requests.get(
            f"{self._base_url}/api/v1/query_range",
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()

        if body.get("status") != "success":
            raise PrometheusQueryError(
                f"Prometheus returned status={body.get('status')}: {body.get('error')}"
            )
        return body["data"]

    def _parse_matrix(self, data: dict) -> list[float]:
        """
        Extract float values from a Prometheus matrix result.

        Prometheus matrix shape:
          {
            "resultType": "matrix",
            "result": [
              { "metric": {...labels...}, "values": [[ts, "val"], ...] },
              ...   # one entry per label combination
            ]
          }

        We sum across all label combinations (pods) to get the cluster-wide
        request rate, then return just the float values in time order.
        """
        if data.get("resultType") != "matrix":
            raise PrometheusQueryError(
                f"Expected resultType=matrix, got {data.get('resultType')!r}"
            )

        results = data.get("result", [])
        if not results:
            return []

        # Build a timestamp-keyed dict and sum across all series (label combos)
        aggregated: dict[float, float] = {}
        for series in results:
            for ts_str, val_str in series.get("values", []):
                ts = float(ts_str)
                val = float(val_str) if val_str != "NaN" else 0.0
                aggregated[ts] = aggregated.get(ts, 0.0) + val

        # Return values sorted by timestamp (chronological)
        return [v for _, v in sorted(aggregated.items())]
