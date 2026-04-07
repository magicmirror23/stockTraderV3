# Gateway URL normalization tests
"""Regression tests for service URL parsing used by the API gateway."""

from backend.api.services.gateway import _normalize_service_url, _timeout_for_path


def test_normalize_service_url_hostport_without_scheme():
    raw = "stocktrader-market-data-lyh3:10000"
    assert _normalize_service_url(raw, "http://localhost:8001") == "http://stocktrader-market-data-lyh3:10000"


def test_normalize_service_url_preserves_http_and_https():
    assert _normalize_service_url("http://svc:8000", "http://localhost:8001") == "http://svc:8000"
    assert _normalize_service_url("https://svc.example.com", "http://localhost:8001") == "https://svc.example.com"


def test_normalize_service_url_uses_fallback_when_blank():
    assert _normalize_service_url("", "http://localhost:8001") == "http://localhost:8001"


def test_timeout_for_path_uses_longer_timeout_for_retrain(monkeypatch):
    monkeypatch.setenv("GATEWAY_UPSTREAM_TIMEOUT_S", "60")
    monkeypatch.setenv("GATEWAY_RETRAIN_TIMEOUT_S", "900")
    assert _timeout_for_path("/api/v1/retrain") == 900.0
    assert _timeout_for_path("/api/v1/retrain/status") == 900.0


def test_timeout_for_path_uses_longer_timeout_for_backtest(monkeypatch):
    monkeypatch.setenv("GATEWAY_UPSTREAM_TIMEOUT_S", "60")
    monkeypatch.setenv("GATEWAY_BACKTEST_TIMEOUT_S", "600")
    assert _timeout_for_path("/api/v1/backtest/run") == 600.0
    assert _timeout_for_path("/api/v1/backtest/abc/results") == 600.0


def test_timeout_for_path_defaults_for_regular_routes(monkeypatch):
    monkeypatch.setenv("GATEWAY_UPSTREAM_TIMEOUT_S", "75")
    assert _timeout_for_path("/api/v1/market/status") == 75.0
