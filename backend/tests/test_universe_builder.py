from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.ml_platform.universe_builder import UniverseBuilder, UniverseFilterConfig


def _make_bars(
    symbol: str,
    *,
    rows: int = 220,
    start: str = "2025-06-02",
    close_base: float = 1000.0,
    volume_base: float = 100_000.0,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=rows)
    idx = pd.Series(range(rows), dtype=float)
    frame = pd.DataFrame(
        {
            "timestamp": dates,
            "open": close_base + idx,
            "high": close_base + idx + 5.0,
            "low": close_base + idx - 5.0,
            "close": close_base + idx + 1.5,
            "volume": volume_base + (idx * 10.0),
            "symbol": symbol,
            "interval": "1d",
            "source": "unit_test",
        }
    )
    return frame


@dataclass
class _FakeStore:
    frames: dict[str, pd.DataFrame]
    failure_counts: dict[str, int] | None = None

    def ensure_schema(self) -> None:
        return None

    def query_bars(self, *, symbol: str, start: str, end: str, interval: str) -> pd.DataFrame:
        frame = self.frames.get(symbol, pd.DataFrame()).copy()
        if frame.empty:
            return frame
        ts = pd.to_datetime(frame["timestamp"])
        mask = (ts >= pd.Timestamp(start)) & (ts <= pd.Timestamp(end))
        return frame.loc[mask].reset_index(drop=True)

    def failure_attempt_counts(
        self,
        *,
        symbols: list[str] | None = None,
        interval: str = "1d",
    ) -> dict[str, int]:
        raw = self.failure_counts or {}
        if not symbols:
            return {str(k): int(v) for k, v in raw.items()}
        return {str(s): int(raw.get(s, 0)) for s in symbols}


def _filters(**overrides: Any) -> UniverseFilterConfig:
    base = UniverseFilterConfig(
        min_median_daily_value=10_000_000.0,
        min_history_days=120,
        min_data_completeness=0.85,
        max_missing_ratio=0.20,
        max_provider_failures=2,
        max_stale_days=5,
        max_zero_volume_ratio=0.30,
        lookback_days=365,
        interval="1d",
    )
    data = base.__dict__.copy()
    data.update(overrides)
    return UniverseFilterConfig(**data)


def test_universe_builder_constructs_snapshot_with_ordered_selection(tmp_path):
    store = _FakeStore(
        frames={
            "AAA": _make_bars("AAA", close_base=800, volume_base=90_000),   # lower liquidity
            "BBB": _make_bars("BBB", close_base=1200, volume_base=130_000),  # highest liquidity
            "CCC": _make_bars("CCC", close_base=1000, volume_base=110_000),  # middle
        },
        failure_counts={"AAA": 0, "BBB": 0, "CCC": 0},
    )
    builder = UniverseBuilder(
        store=store,
        filters=_filters(),
        snapshot_root=tmp_path / "snapshots",
        candidate_overrides={"universe_v2": ["AAA", "BBB", "CCC"]},
    )

    snapshot = builder.build_snapshot(version="universe_v2", as_of_date="2026-04-01")
    assert snapshot["universe_version"] == "universe_v2"
    assert snapshot["candidate_count"] == 3
    assert snapshot["selected_count"] == 3
    assert snapshot["selected_symbols"] == ["BBB", "CCC", "AAA"]
    assert snapshot["symbol_tags"]["AAA"]["sector"]  # tags present


def test_universe_builder_applies_liquidity_filter(tmp_path):
    store = _FakeStore(
        frames={
            "AAA": _make_bars("AAA", close_base=1200, volume_base=140_000),  # liquid
            "BBB": _make_bars("BBB", close_base=90, volume_base=8_000),      # illiquid
        },
        failure_counts={"AAA": 0, "BBB": 0},
    )
    builder = UniverseBuilder(
        store=store,
        filters=_filters(min_median_daily_value=50_000_000.0),
        snapshot_root=tmp_path / "snapshots",
        candidate_overrides={"universe_v3": ["AAA", "BBB"]},
    )

    snapshot = builder.build_snapshot(version="universe_v3", as_of_date="2026-04-01")
    assert snapshot["selected_symbols"] == ["AAA"]
    assert "BBB" in snapshot["excluded_symbols"]
    assert "illiquid" in snapshot["excluded_symbols"]["BBB"]


def test_universe_snapshot_reproducibility_uses_existing_snapshot(tmp_path):
    store = _FakeStore(
        frames={"AAA": _make_bars("AAA", close_base=1100, volume_base=120_000)},
        failure_counts={"AAA": 0},
    )
    builder = UniverseBuilder(
        store=store,
        filters=_filters(),
        snapshot_root=tmp_path / "snapshots",
        candidate_overrides={"universe_v4": ["AAA"]},
    )

    first = builder.build_snapshot(version="universe_v4", as_of_date="2026-04-01")

    # Mutate source data; second call should still return persisted snapshot.
    store.frames["AAA"] = _make_bars("AAA", close_base=20, volume_base=100)
    second = builder.build_snapshot(version="universe_v4", as_of_date="2026-04-01")

    assert first["snapshot_path"] == second["snapshot_path"]
    assert first["selected_symbols"] == second["selected_symbols"]
    assert first["generated_at"] == second["generated_at"]


def test_universe_builder_excludes_bad_symbols_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIVERSE_BAD_SYMBOLS", "AAA")
    store = _FakeStore(
        frames={
            "AAA": _make_bars("AAA", close_base=1300, volume_base=140_000),
            "BBB": _make_bars("BBB", close_base=1200, volume_base=130_000),
        },
        failure_counts={"AAA": 0, "BBB": 0},
    )
    builder = UniverseBuilder(
        store=store,
        filters=_filters(),
        snapshot_root=tmp_path / "snapshots",
        candidate_overrides={"universe_v2": ["AAA", "BBB"]},
    )

    snapshot = builder.build_snapshot(version="universe_v2", as_of_date="2026-04-01")
    assert snapshot["selected_symbols"] == ["BBB"]
    assert "AAA" in snapshot["excluded_symbols"]
    assert "bad_symbol_list" in snapshot["excluded_symbols"]["AAA"]

