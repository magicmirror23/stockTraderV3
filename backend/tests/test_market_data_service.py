from __future__ import annotations

import pandas as pd

from backend.market_data_service.errors import ProviderFailure, ERROR_RATE_LIMITED
from backend.market_data_service.orchestrator import MarketDataOrchestrator
from backend.market_data_service.providers.base import MarketDataProvider
from backend.market_data_service.storage import MarketDataStore
from backend.market_data_service.symbols import SymbolResolver


class _FailingProvider(MarketDataProvider):
    name = "failing"

    def get_historical_bars(self, symbol, start_date, end_date, interval):
        raise ProviderFailure(
            "rate limited",
            code=ERROR_RATE_LIMITED,
            provider=self.name,
            retryable=True,
        )

    def get_latest_quote(self, symbol):
        raise ProviderFailure("no quote", provider=self.name)

    def get_market_status(self, exchange):
        return {"exchange": exchange, "status": "unknown"}

    def search_symbol(self, symbol):
        return {"symbol": symbol}


class _WorkingProvider(MarketDataProvider):
    name = "working"

    def get_historical_bars(self, symbol, start_date, end_date, interval):
        dates = pd.date_range("2026-01-01", periods=30, freq="B")
        base = pd.Series(range(len(dates)), dtype=float)
        return pd.DataFrame(
            {
                "Date": dates,
                "Open": 100.0 + base,
                "High": 101.0 + base,
                "Low": 99.0 + base,
                "Close": 100.5 + base,
                "Volume": 10_000 + base,
            }
        )

    def get_latest_quote(self, symbol):
        return {"symbol": symbol, "price": 100.0, "provider": self.name}

    def get_market_status(self, exchange):
        return {"exchange": exchange, "status": "open", "provider": self.name}

    def search_symbol(self, symbol):
        return {"symbol": symbol, "provider": self.name}



def _seed_symbol(symbol: str = "TESTMDS", rows: int = 25) -> None:
    store = MarketDataStore()
    dates = pd.date_range("2026-02-01", periods=rows, freq="B")
    base = pd.Series(range(len(dates)), dtype=float)
    frame = pd.DataFrame(
        {
            "timestamp": dates,
            "open": 200.0 + base,
            "high": 201.0 + base,
            "low": 199.0 + base,
            "close": 200.5 + base,
            "volume": 5_000 + base,
            "symbol": symbol,
            "interval": "1d",
            "source": "unit_test",
        }
    )
    store.upsert_bars(frame)



def test_symbol_resolver_maps_indian_tickers():
    resolver = SymbolResolver()
    assert resolver.to_yahoo("RELIANCE") == "RELIANCE.NS"
    assert resolver.to_yahoo("TATAMOTORS") == "TATAMOTORS.NS"
    assert resolver.to_twelve_data("RELIANCE") == "RELIANCE:NSE"



def test_orchestrator_fallback_provider_chain(monkeypatch):
    orchestrator = MarketDataOrchestrator()
    orchestrator.max_retries = 1
    orchestrator.historical_providers = [_FailingProvider(), _WorkingProvider()]

    result = orchestrator.fetch_historical(
        symbol="RELIANCE",
        start_date="2026-01-01",
        end_date="2026-03-15",
        interval="1d",
        min_rows=20,
        force=True,
    )

    assert result["status"] == "ok"
    assert result["source"] == "working"
    assert result["rows"] >= 20



def test_orchestrator_sets_cooldown_on_repeated_failures():
    orchestrator = MarketDataOrchestrator()
    orchestrator.max_retries = 1
    orchestrator.failure_threshold = 1
    orchestrator.cooldown_s = 60
    orchestrator.historical_providers = [_FailingProvider()]

    try:
        orchestrator.fetch_historical(
            symbol="FAILSYM",
            start_date="2026-01-01",
            end_date="2026-02-01",
            interval="1d",
            min_rows=5,
            force=True,
        )
    except ProviderFailure:
        pass

    remaining = orchestrator.cache.cooldown_remaining("provider", "failing")
    assert remaining > 0



def test_store_upsert_deduplicates_market_bars():
    store = MarketDataStore()
    symbol = "DEDUPTEST"
    ts = pd.Timestamp("2026-03-01")

    frame = pd.DataFrame(
        [
            {
                "timestamp": ts,
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.2,
                "volume": 1000,
                "symbol": symbol,
                "interval": "1d",
                "source": "unit_test",
            },
            {
                "timestamp": ts,
                "open": 11.0,
                "high": 11.5,
                "low": 10.5,
                "close": 11.2,
                "volume": 1200,
                "symbol": symbol,
                "interval": "1d",
                "source": "unit_test",
            },
        ]
    )

    store.upsert_bars(frame)
    queried = store.query_bars(symbol=symbol, start="2026-02-28", end="2026-03-05", interval="1d")
    assert len(queried) == 1
    assert float(queried.iloc[0]["close"]) in {10.2, 11.2}



def test_historical_query_endpoint_returns_rows(client):
    _seed_symbol(symbol="APIQTEST", rows=28)
    res = client.get(
        "/api/v1/historical/query",
        params={
            "symbol": "APIQTEST",
            "start_date": "2026-02-01",
            "end_date": "2026-03-31",
            "interval": "1d",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["rows"] >= 20



def test_symbols_resolve_endpoint(client):
    res = client.post("/api/v1/symbols/resolve", json={"symbol": "RELIANCE"})
    assert res.status_code == 200
    body = res.json()
    assert body["resolved"]["canonical_symbol"] == "RELIANCE"


def test_retry_failed_symbols_drops_unknown_symbols(monkeypatch):
    orchestrator = MarketDataOrchestrator()
    monkeypatch.setenv("MDS_RETRY_STRICT_SYMBOL_FILTER", "true")

    monkeypatch.setattr(orchestrator.store, "get_retry_candidates", lambda interval="1d", limit=100: ["FAILSYM", "RELIANCE"])
    dropped_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        orchestrator.store,
        "clear_failure",
        lambda symbol, interval: dropped_calls.append((symbol, interval)),
    )

    captured: dict[str, object] = {}

    def _fake_backfill(symbols, years, interval, min_rows):
        captured["symbols"] = symbols
        return {
            "job": "backfill_historical_data",
            "status": "ok",
            "requested": len(symbols),
            "successful": len(symbols),
            "failed": 0,
            "results": [],
        }

    monkeypatch.setattr(orchestrator, "job_backfill_historical_data", _fake_backfill)

    out = orchestrator.job_retry_failed_symbols(interval="1d", limit=20)

    assert captured["symbols"] == ["RELIANCE"]
    assert out["dropped_unknown_symbols"] == ["FAILSYM"]
    assert ("FAILSYM", "1d") in dropped_calls
