"""Universe builder with tradability filters and snapshot reproducibility."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.market_data_service.storage import MarketDataStore
from backend.market_data_service.symbols import SymbolResolver

from .universe_definitions import (
    UNIVERSE_LABELS,
    get_symbol_tags,
    get_universe_candidates,
)


@dataclass(frozen=True)
class UniverseFilterConfig:
    min_median_daily_value: float = 50_000_000.0
    min_history_days: int = 180
    min_data_completeness: float = 0.90
    max_missing_ratio: float = 0.10
    max_provider_failures: int = 3
    max_stale_days: int = 10
    max_zero_volume_ratio: float = 0.15
    lookback_days: int = 365
    interval: str = "1d"

    @classmethod
    def from_env(cls) -> "UniverseFilterConfig":
        return cls(
            min_median_daily_value=float(os.getenv("UNIVERSE_MIN_MEDIAN_DAILY_VALUE", "50000000")),
            min_history_days=int(os.getenv("UNIVERSE_MIN_HISTORY_DAYS", "180")),
            min_data_completeness=float(os.getenv("UNIVERSE_MIN_COMPLETENESS", "0.90")),
            max_missing_ratio=float(os.getenv("UNIVERSE_MAX_MISSING_RATIO", "0.10")),
            max_provider_failures=int(os.getenv("UNIVERSE_MAX_PROVIDER_FAILURES", "3")),
            max_stale_days=int(os.getenv("UNIVERSE_MAX_STALE_DAYS", "10")),
            max_zero_volume_ratio=float(os.getenv("UNIVERSE_MAX_ZERO_VOLUME_RATIO", "0.15")),
            lookback_days=int(os.getenv("UNIVERSE_LOOKBACK_DAYS", "365")),
            interval=os.getenv("UNIVERSE_INTERVAL", "1d").strip() or "1d",
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


class UniverseBuilder:
    """Constructs and persists point-in-time universe snapshots."""

    def __init__(
        self,
        *,
        store: MarketDataStore | None = None,
        resolver: SymbolResolver | None = None,
        filters: UniverseFilterConfig | None = None,
        snapshot_root: str | Path | None = None,
        candidate_overrides: dict[str, list[str]] | None = None,
    ) -> None:
        self.store = store or MarketDataStore()
        self.store.ensure_schema()
        self.resolver = resolver or SymbolResolver()
        self.filters = filters or UniverseFilterConfig.from_env()
        self.snapshot_root = Path(
            snapshot_root
            or os.getenv("UNIVERSE_SNAPSHOT_DIR", str(Path(__file__).resolve().parents[2] / "storage" / "universes"))
        )
        self.candidate_overrides = candidate_overrides or {}

    def _resolve_as_of_date(self, as_of_date: str | datetime | None) -> datetime:
        if as_of_date is None:
            return _utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        ts = pd.Timestamp(as_of_date)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0)

    def _snapshot_path(self, version: str, as_of_ts: datetime) -> Path:
        date_key = as_of_ts.date().isoformat()
        return self.snapshot_root / version / f"{date_key}.json"

    def load_snapshot(self, version: str, as_of_date: str | datetime | None = None) -> dict[str, Any] | None:
        as_of_ts = self._resolve_as_of_date(as_of_date)
        path = self._snapshot_path(version, as_of_ts)
        if not path.exists():
            return None
        payload = json.loads(path.read_text())
        if isinstance(payload, dict):
            payload["snapshot_path"] = str(path)
        return payload if isinstance(payload, dict) else None

    def _candidate_symbols(self, version: str) -> list[str]:
        key = str(version).strip().lower()
        if key in self.candidate_overrides:
            return [self.resolver.normalize(s) for s in self.candidate_overrides[key]]
        return [self.resolver.normalize(s) for s in get_universe_candidates(key)]

    def _bad_symbol_set(self) -> set[str]:
        bad: set[str] = set()
        raw = os.getenv("UNIVERSE_BAD_SYMBOLS", "").strip()
        if raw:
            bad.update(self.resolver.normalize(x) for x in raw.split(",") if x.strip())

        bad_file = Path(
            os.getenv(
                "UNIVERSE_BAD_SYMBOLS_FILE",
                str(self.snapshot_root / "bad_symbols.json"),
            )
        )
        if bad_file.exists():
            try:
                data = json.loads(bad_file.read_text())
                if isinstance(data, list):
                    bad.update(self.resolver.normalize(x) for x in data if str(x).strip())
            except Exception:
                pass
        return bad

    def _failure_counts(self, symbols: list[str], interval: str) -> dict[str, int]:
        return self.store.failure_attempt_counts(symbols=symbols, interval=interval)

    def _symbol_metrics(
        self,
        *,
        symbol: str,
        as_of_ts: datetime,
        failure_attempts: int,
    ) -> dict[str, Any]:
        start = (as_of_ts.date() - timedelta(days=max(30, int(self.filters.lookback_days)))).isoformat()
        end = as_of_ts.date().isoformat()
        frame = self.store.query_bars(
            symbol=symbol,
            start=start,
            end=end,
            interval=self.filters.interval,
        )

        if frame.empty:
            return {
                "history_days": 0,
                "expected_days": 0,
                "data_completeness": 0.0,
                "missing_ratio": 1.0,
                "median_daily_value": 0.0,
                "zero_volume_ratio": 1.0,
                "stale_days": 9999,
                "provider_failure_attempts": int(failure_attempts),
                "rows": 0,
            }

        frame = frame.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

        row_count = int(len(frame))
        history_days = int(frame["timestamp"].nunique())
        first_date = frame["timestamp"].min().date()
        last_date = frame["timestamp"].max().date()
        expected_days = int(len(pd.bdate_range(first_date, as_of_ts.date())))
        expected_days = max(expected_days, 1)

        ohlcv = frame[["open", "high", "low", "close", "volume"]].copy()
        data_completeness = float(1.0 - float(ohlcv.isna().mean().mean()))
        data_completeness = max(0.0, min(1.0, data_completeness))

        completeness = float(history_days / expected_days)
        completeness = max(0.0, min(1.0, completeness))
        missing_ratio = float(max(0.0, 1.0 - completeness))

        traded_value = (frame["close"].fillna(0.0).clip(lower=0.0) * frame["volume"].fillna(0.0).clip(lower=0.0))
        median_daily_value = float(traded_value.median()) if not traded_value.empty else 0.0
        zero_volume_ratio = float((frame["volume"].fillna(0.0) <= 0.0).mean())
        stale_days = int(max(0, (as_of_ts.date() - last_date).days))

        return {
            "history_days": history_days,
            "expected_days": expected_days,
            "data_completeness": round(data_completeness, 6),
            "missing_ratio": round(missing_ratio, 6),
            "median_daily_value": round(median_daily_value, 2),
            "zero_volume_ratio": round(zero_volume_ratio, 6),
            "stale_days": stale_days,
            "provider_failure_attempts": int(failure_attempts),
            "rows": row_count,
        }

    def _rejection_reasons(self, symbol: str, metrics: dict[str, Any], bad_symbols: set[str]) -> list[str]:
        reasons: list[str] = []
        if symbol in bad_symbols:
            reasons.append("bad_symbol_list")
        if metrics["history_days"] < self.filters.min_history_days:
            reasons.append("insufficient_history")
        if metrics["data_completeness"] < self.filters.min_data_completeness:
            reasons.append("low_data_completeness")
        if metrics["missing_ratio"] > self.filters.max_missing_ratio:
            reasons.append("high_missing_ratio")
        if metrics["median_daily_value"] < self.filters.min_median_daily_value:
            reasons.append("illiquid")
        if metrics["provider_failure_attempts"] > self.filters.max_provider_failures:
            reasons.append("unstable_provider_failures")
        if metrics["stale_days"] > self.filters.max_stale_days:
            reasons.append("stale_data")
        if metrics["zero_volume_ratio"] > self.filters.max_zero_volume_ratio:
            reasons.append("high_zero_volume_ratio")
        return reasons

    def build_snapshot(
        self,
        *,
        version: str,
        as_of_date: str | datetime | None = None,
        force_rebuild: bool = False,
    ) -> dict[str, Any]:
        key = str(version).strip().lower()
        as_of_ts = self._resolve_as_of_date(as_of_date)
        snapshot_path = self._snapshot_path(key, as_of_ts)
        if snapshot_path.exists() and not force_rebuild:
            payload = json.loads(snapshot_path.read_text())
            payload["snapshot_path"] = str(snapshot_path)
            return payload

        candidates = self._candidate_symbols(key)
        bad_symbols = self._bad_symbol_set()
        failure_counts = self._failure_counts(candidates, interval=self.filters.interval)

        selected_with_liquidity: list[tuple[str, float]] = []
        excluded: dict[str, list[str]] = {}
        metrics_by_symbol: dict[str, dict[str, Any]] = {}
        tags_by_symbol: dict[str, dict[str, str]] = {}

        for symbol in candidates:
            m = self._symbol_metrics(
                symbol=symbol,
                as_of_ts=as_of_ts,
                failure_attempts=int(failure_counts.get(symbol, 0)),
            )
            metrics_by_symbol[symbol] = m
            tags_by_symbol[symbol] = get_symbol_tags(symbol)
            reasons = self._rejection_reasons(symbol, m, bad_symbols)
            if reasons:
                excluded[symbol] = reasons
            else:
                selected_with_liquidity.append((symbol, float(m["median_daily_value"])))

        selected_symbols = [sym for sym, _ in sorted(selected_with_liquidity, key=lambda row: row[1], reverse=True)]

        snapshot = {
            "universe_version": key,
            "universe_label": UNIVERSE_LABELS.get(key, key),
            "as_of_date": as_of_ts.date().isoformat(),
            "generated_at": _now_iso(),
            "filters": asdict(self.filters),
            "candidate_count": len(candidates),
            "selected_count": len(selected_symbols),
            "selected_symbols": selected_symbols,
            "excluded_symbols": excluded,
            "symbol_metrics": metrics_by_symbol,
            "symbol_tags": tags_by_symbol,
            "bad_symbol_list": sorted(bad_symbols),
        }

        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot, indent=2))
        snapshot["snapshot_path"] = str(snapshot_path)
        return snapshot

    def get_symbols(
        self,
        *,
        version: str,
        as_of_date: str | datetime | None = None,
        force_rebuild: bool = False,
    ) -> list[str]:
        snapshot = self.build_snapshot(
            version=version,
            as_of_date=as_of_date,
            force_rebuild=force_rebuild,
        )
        return list(snapshot.get("selected_symbols", []))
