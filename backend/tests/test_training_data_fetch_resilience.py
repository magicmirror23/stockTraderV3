from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.market_data_service.storage import MarketDataStore
from backend.prediction_engine.training.trainer import (
    TrainingConfig,
    _ensure_data_available,
)


def _make_ohlcv(rows: int) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    base = pd.Series(range(rows), dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": 100 + base,
            "High": 101 + base,
            "Low": 99 + base,
            "Close": 100 + base,
            "Volume": 1_000 + base.astype(int),
        }
    )


def test_ensure_data_refreshes_undersized_csv(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Existing file is present but too short to support training windows.
    _make_ohlcv(80).to_csv(data_dir / "RELIANCE.csv", index=False)

    # Seed canonical local store so trainer can hydrate CSV from DB without
    # calling external providers.
    store = MarketDataStore()
    seeded = _make_ohlcv(250).rename(
        columns={
            "Date": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    seeded["symbol"] = "RELIANCE"
    seeded["interval"] = "1d"
    seeded["source"] = "unit_test"
    store.upsert_bars(seeded)

    monkeypatch.setenv("TRAIN_DOWNLOAD_MIN_RAW_ROWS", "200")
    monkeypatch.setenv("TRAIN_DOWNLOAD_LOOKBACK_DAYS", "730")
    monkeypatch.setenv("TRAIN_DATA_SOURCE_MODE", "local_store_only")

    cfg = TrainingConfig(
        train_min_days=20,
        val_min_days=5,
        test_min_days=5,
        purge_gap_days=1,
        min_unique_dates=20,
        min_rows_per_symbol=80,
        min_symbols=1,
        min_samples_per_class=1,
    )
    available, report = _ensure_data_available(
        ["RELIANCE"],
        data_dir,
        config=cfg,
        return_report=True,
    )

    assert available == ["RELIANCE"]
    assert report["hydrated"] == ["RELIANCE"]
    assert report["raw_rows_available"]["RELIANCE"] >= 200
    assert len(pd.read_csv(data_dir / "RELIANCE.csv")) >= 200


def test_ensure_data_skips_download_when_existing_is_sufficient(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    _make_ohlcv(450).to_csv(data_dir / "RELIANCE.csv", index=False)
    _make_ohlcv(460).to_csv(data_dir / "TCS.csv", index=False)

    calls = {"count": 0}

    class _NeverCalledConnector:
        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, ticker, start, end):  # pragma: no cover - should not run
            calls["count"] += 1
            raise AssertionError("fetch() should not be called for sufficient existing CSVs")

    monkeypatch.setenv("TRAIN_DOWNLOAD_MIN_RAW_ROWS", "400")
    monkeypatch.setattr(
        "backend.prediction_engine.data_pipeline.connector_yahoo.YahooConnector",
        _NeverCalledConnector,
    )

    cfg = TrainingConfig(
        train_min_days=20,
        val_min_days=5,
        test_min_days=5,
        purge_gap_days=1,
        min_unique_dates=20,
        min_rows_per_symbol=80,
        min_symbols=1,
        min_samples_per_class=1,
    )
    available, report = _ensure_data_available(
        ["RELIANCE", "TCS"],
        data_dir,
        config=cfg,
        return_report=True,
    )

    assert set(available) == {"RELIANCE", "TCS"}
    assert report["downloaded"] == []
    assert calls["count"] == 0
