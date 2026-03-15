"""
test_prometheus_client.py
-------------------------
Unit tests for the Prometheus HTTP client.

All HTTP calls are mocked — no real Prometheus server is needed.

Coverage:
  - Successful range query parsing
  - Multi-series aggregation (sum across label combos)
  - Empty result handling
  - HTTP error resilience
  - Connectivity error resilience
  - NaN value handling from Prometheus
"""

import pytest
from unittest.mock import patch, MagicMock

from autoscaler.config import load_config
from autoscaler.prometheus_client import PrometheusClient, PrometheusQueryError


@pytest.fixture
def client():
    return PrometheusClient(load_config())


def _make_matrix_response(series: list) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"pod": f"pod-{i}"},
                    "values": [[str(ts), str(val)] for ts, val in values],
                }
                for i, values in enumerate(series)
            ],
        },
    }


class TestParsing:
    def test_single_series_parsed_correctly(self, client):
        values = [(1000.0 + i, float(i * 10)) for i in range(5)]
        data = _make_matrix_response([values])["data"]
        result = client._parse_matrix(data)
        assert result == [0.0, 10.0, 20.0, 30.0, 40.0]

    def test_multi_series_summed(self, client):
        values = [(1000.0, 50.0), (1005.0, 50.0)]
        data = _make_matrix_response([values, values])["data"]
        result = client._parse_matrix(data)
        assert all(v == pytest.approx(100.0) for v in result)

    def test_empty_result_returns_empty_list(self, client):
        data = {"resultType": "matrix", "result": []}
        result = client._parse_matrix(data)
        assert result == []

    def test_nan_values_replaced_with_zero(self, client):
        data = {
            "resultType": "matrix",
            "result": [{"metric": {}, "values": [["1000.0", "NaN"], ["1005.0", "50.0"]]}],
        }
        result = client._parse_matrix(data)
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(50.0)

    def test_wrong_result_type_raises(self, client):
        data = {"resultType": "vector", "result": []}
        with pytest.raises(PrometheusQueryError):
            client._parse_matrix(data)


class TestHTTPBehaviour:
    def test_successful_fetch_returns_floats(self, client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _make_matrix_response(
            [[(1000.0 + i * 5, 100.0) for i in range(10)]]
        )
        with patch("autoscaler.prometheus_client.requests.get", return_value=mock_resp):
            result = client.fetch_request_rate()
        assert len(result) == 10
        assert all(v == pytest.approx(100.0) for v in result)

    def test_http_error_returns_empty_list(self, client):
        import requests as req
        with patch("autoscaler.prometheus_client.requests.get",
                   side_effect=req.HTTPError("503")):
            result = client.fetch_request_rate()
        assert result == []

    def test_connection_error_returns_empty_list(self, client):
        import requests as req
        with patch("autoscaler.prometheus_client.requests.get",
                   side_effect=req.ConnectionError("refused")):
            result = client.fetch_request_rate()
        assert result == []

    def test_prometheus_error_status_returns_empty_list(self, client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "error",
            "error": "bad_data",
            "errorType": "bad_data",
        }
        with patch("autoscaler.prometheus_client.requests.get", return_value=mock_resp):
            result = client.fetch_request_rate()
        assert result == []
