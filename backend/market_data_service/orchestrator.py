"""Orchestrates provider fallback, retries, cooldown, and persistence."""

from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .cache import CacheBackend
from .errors import (
    ProviderFailure,
    ERROR_ALL_PROVIDERS_FAILED,
    ERROR_COOLDOWN,
    ERROR_PROVIDER_UNAVAILABLE,
)
from .providers import (
    MarketDataProvider,
    YahooFinanceProvider,
    TwelveDataProvider,
    NSEEnrichmentProvider,
    ZerodhaKiteProvider,
)
from .storage import MarketDataStore
from .symbols import SymbolResolver
from .validators import frame_to_api_rows, normalize_ohlcv_frame

logger = logging.getLogger(__name__)


class MarketDataOrchestrator:
    """Single entry-point for fetching, validating, storing, and querying market data."""

    def __init__(self) -> None:
        self.resolver = SymbolResolver()
        self.cache = CacheBackend()
        self.store = MarketDataStore()
        self.store.ensure_schema()

        self.max_retries = int(os.getenv("MDS_PROVIDER_MAX_RETRIES", "2"))
        self.backoff_base_s = float(os.getenv("MDS_BACKOFF_BASE_S", "1.4"))
        self.backoff_jitter_s = float(os.getenv("MDS_BACKOFF_JITTER_S", "0.7"))
        self.cooldown_s = int(os.getenv("MDS_PROVIDER_COOLDOWN_S", "180"))
        self.failure_threshold = int(os.getenv("MDS_PROVIDER_FAILURE_THRESHOLD", "3"))
        self.failure_window_s = int(os.getenv("MDS_PROVIDER_FAILURE_WINDOW_S", "300"))

        self.historical_cache_ttl_s = int(os.getenv("MDS_HISTORICAL_CACHE_TTL_S", "90"))
        self.quote_cache_ttl_s = int(os.getenv("MDS_QUOTE_CACHE_TTL_S", "10"))

        twelve_api_key = os.getenv("TWELVE_DATA_API_KEY", "")
        self.yahoo = YahooFinanceProvider(self.resolver)
        self.twelve = TwelveDataProvider(api_key=twelve_api_key, resolver=self.resolver)
        self.nse = NSEEnrichmentProvider(self.resolver)
        self.kite = ZerodhaKiteProvider()

        self.historical_providers: list[MarketDataProvider] = [self.yahoo, self.twelve, self.kite]
        self.quote_providers: list[MarketDataProvider] = [self.yahoo, self.twelve, self.kite]

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _env_bool(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}

    def _known_retry_universe(self, interval: str = "1d") -> set[str]:
        """Known symbols allowed for automatic retry jobs.

        Includes:
        1) static tracked universe from SYMBOL_CATEGORIES
        2) any symbol already persisted in local market_bars
        3) optional env-injected symbols (MDS_RETRY_EXTRA_SYMBOLS)
        """
        known: set[str] = set()
        try:
            from backend.services.price_feed import SYMBOL_CATEGORIES

            for symbols in SYMBOL_CATEGORIES.values():
                for symbol in symbols:
                    if symbol:
                        known.add(str(symbol).strip().upper())
        except Exception:
            pass

        try:
            for symbol in self.store.list_symbols(interval=interval):
                known.add(str(symbol).strip().upper())
        except Exception:
            pass

        extra = [
            s.strip().upper()
            for s in os.getenv("MDS_RETRY_EXTRA_SYMBOLS", "").split(",")
            if s.strip()
        ]
        known.update(extra)
        return known

    def _filter_retry_candidates(self, symbols: list[str], interval: str) -> tuple[list[str], list[str]]:
        strict = self._env_bool("MDS_RETRY_STRICT_SYMBOL_FILTER", True)
        if not strict:
            normalized = [self.resolver.resolve(s).canonical_symbol for s in symbols if str(s).strip()]
            return normalized, []

        known = self._known_retry_universe(interval=interval)
        eligible: list[str] = []
        dropped: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            if not str(symbol).strip():
                continue
            canonical = self.resolver.resolve(symbol).canonical_symbol
            if canonical in seen:
                continue
            seen.add(canonical)
            if canonical in known:
                eligible.append(canonical)
            else:
                dropped.append(canonical)

        for symbol in dropped:
            # Remove noisy unknown symbols (e.g., test artifacts) from retry queue.
            self.store.clear_failure(symbol, interval)
        if dropped:
            logger.info(
                "Skipping %d unknown retry symbols and clearing their failure rows: %s",
                len(dropped),
                dropped,
            )
        return eligible, dropped

    def _provider_cooldown_remaining(self, provider_name: str) -> float:
        return self.cache.cooldown_remaining("provider", provider_name)

    def _symbol_cooldown_remaining(self, symbol: str) -> float:
        return self.cache.cooldown_remaining("symbol", symbol)

    def _mark_failure(self, provider_name: str, symbol: str, interval: str, failure: ProviderFailure) -> None:
        key = f"failure:{provider_name}:{symbol}:{interval}"
        count = self.cache.incr_with_ttl(key, ttl_s=self.failure_window_s)
        if count >= self.failure_threshold:
            self.cache.set_cooldown("provider", provider_name, self.cooldown_s)
            self.cache.set_cooldown("symbol", symbol, self.cooldown_s)

        self.store.save_failure(
            symbol=symbol,
            interval=interval,
            provider=provider_name,
            error_code=failure.code,
            message=failure.message,
            cooldown_seconds=self.cooldown_s,
        )

    def _check_cooldowns(self, provider_name: str, symbol: str) -> None:
        provider_cd = self._provider_cooldown_remaining(provider_name)
        if provider_cd > 0:
            raise ProviderFailure(
                f"Provider {provider_name} is cooling down.",
                code=ERROR_COOLDOWN,
                provider=provider_name,
                details={"cooldown_remaining_s": round(provider_cd, 3)},
                retryable=True,
            )

        symbol_cd = self._symbol_cooldown_remaining(symbol)
        if symbol_cd > 0:
            raise ProviderFailure(
                f"Symbol {symbol} is cooling down.",
                code=ERROR_COOLDOWN,
                provider=provider_name,
                details={"symbol": symbol, "cooldown_remaining_s": round(symbol_cd, 3)},
                retryable=True,
            )

    def resolve_symbol(self, symbol: str) -> dict[str, Any]:
        resolved = self.resolver.resolve(symbol)
        return {
            "input_symbol": resolved.input_symbol,
            "canonical_symbol": resolved.canonical_symbol,
            "exchange": resolved.exchange,
            "yahoo_symbol": resolved.yahoo_symbol,
            "twelve_data_symbol": resolved.twelve_data_symbol,
            "is_index": resolved.is_index,
        }

    def search_symbol(self, symbol: str) -> dict[str, Any]:
        resolved = self.resolve_symbol(symbol)
        provider_results: list[dict[str, Any]] = []
        for provider in [self.yahoo, self.twelve, self.nse, self.kite]:
            try:
                provider_results.append({"provider": provider.name, "result": provider.search_symbol(symbol)})
            except Exception as exc:
                provider_results.append({"provider": provider.name, "error": str(exc)})
        return {"resolved": resolved, "providers": provider_results}

    def _cache_key_historical(self, symbol: str, start: str, end: str, interval: str) -> str:
        return f"historical:{symbol}:{interval}:{start}:{end}"

    def query_historical(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        limit: int | None = None,
    ) -> pd.DataFrame:
        resolved = self.resolver.resolve(symbol)
        key = self._cache_key_historical(resolved.canonical_symbol, start_date, end_date, interval)
        if limit is None:
            cached = self.cache.get_json(key)
            if isinstance(cached, list):
                frame = pd.DataFrame(cached)
                if not frame.empty:
                    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
                    return frame

        frame = self.store.query_bars(
            symbol=resolved.canonical_symbol,
            start=start_date,
            end=end_date,
            interval=interval,
            limit=limit,
        )
        if limit is None and not frame.empty:
            self.cache.set_json(key, frame_to_api_rows(frame), ttl_s=self.historical_cache_ttl_s)
        return frame

    def fetch_historical(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        min_rows: int = 20,
        force: bool = False,
    ) -> dict[str, Any]:
        resolved = self.resolver.resolve(symbol)

        if not force:
            local = self.query_historical(
                symbol=resolved.canonical_symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
            if len(local) >= max(1, int(min_rows)):
                return {
                    "status": "ok",
                    "symbol": resolved.canonical_symbol,
                    "interval": interval,
                    "source": "local_store",
                    "rows": int(len(local)),
                    "rows_stored": 0,
                    "start": start_date,
                    "end": end_date,
                    "errors": [],
                }

        errors: list[dict[str, Any]] = []

        for provider in self.historical_providers:
            provider_name = provider.name
            if not provider.supports_historical():
                continue

            try:
                self._check_cooldowns(provider_name, resolved.canonical_symbol)
            except ProviderFailure as cooldown_exc:
                errors.append(cooldown_exc.to_dict())
                continue

            for attempt in range(1, self.max_retries + 1):
                try:
                    raw = provider.get_historical_bars(
                        resolved.canonical_symbol,
                        start_date,
                        end_date,
                        interval,
                    )
                    normalized = normalize_ohlcv_frame(
                        raw,
                        symbol=resolved.canonical_symbol,
                        interval=interval,
                        source=provider_name,
                        min_rows=min_rows,
                    )
                    rows_stored = self.store.upsert_bars(normalized)
                    self.store.clear_failure(resolved.canonical_symbol, interval)

                    # Warm query cache with fresh data.
                    key = self._cache_key_historical(resolved.canonical_symbol, start_date, end_date, interval)
                    self.cache.set_json(key, frame_to_api_rows(normalized), ttl_s=self.historical_cache_ttl_s)

                    return {
                        "status": "ok",
                        "symbol": resolved.canonical_symbol,
                        "interval": interval,
                        "source": provider_name,
                        "rows": int(len(normalized)),
                        "rows_stored": int(rows_stored),
                        "start": start_date,
                        "end": end_date,
                        "errors": errors,
                    }
                except ProviderFailure as failure:
                    self._mark_failure(provider_name, resolved.canonical_symbol, interval, failure)
                    errors.append(failure.to_dict())

                    if not failure.retryable or attempt >= self.max_retries:
                        break
                    backoff = self.backoff_base_s * (2 ** (attempt - 1))
                    backoff += random.uniform(0.0, self.backoff_jitter_s)
                    logger.warning(
                        "Provider %s failed (%s attempt %d/%d). Retrying in %.2fs",
                        provider_name,
                        resolved.canonical_symbol,
                        attempt,
                        self.max_retries,
                        backoff,
                    )
                    time.sleep(backoff)
                except Exception as exc:  # pragma: no cover - defensive
                    failure = ProviderFailure(
                        str(exc),
                        code=ERROR_PROVIDER_UNAVAILABLE,
                        provider=provider_name,
                        details={"symbol": resolved.canonical_symbol},
                        retryable=True,
                    )
                    self._mark_failure(provider_name, resolved.canonical_symbol, interval, failure)
                    errors.append(failure.to_dict())
                    if attempt >= self.max_retries:
                        break

        raise ProviderFailure(
            f"All providers failed for {resolved.canonical_symbol}",
            code=ERROR_ALL_PROVIDERS_FAILED,
            provider=None,
            details={
                "symbol": resolved.canonical_symbol,
                "interval": interval,
                "errors": errors,
                "start": start_date,
                "end": end_date,
            },
            retryable=True,
        )

    def get_quote(self, symbol: str, refresh: bool = False) -> dict[str, Any]:
        resolved = self.resolver.resolve(symbol)
        cache_key = f"quote:{resolved.canonical_symbol}"
        if not refresh:
            cached = self.cache.get_json(cache_key)
            if isinstance(cached, dict) and cached:
                return cached

        local_quote = self.store.latest_quote(resolved.canonical_symbol)
        if local_quote and not refresh:
            self.cache.set_json(cache_key, local_quote, ttl_s=self.quote_cache_ttl_s)
            return local_quote

        errors: list[dict[str, Any]] = []
        for provider in self.quote_providers:
            provider_name = provider.name
            try:
                self._check_cooldowns(provider_name, resolved.canonical_symbol)
                quote = provider.get_latest_quote(resolved.canonical_symbol)
                quote["symbol"] = resolved.canonical_symbol
                self.cache.set_json(cache_key, quote, ttl_s=self.quote_cache_ttl_s)
                return quote
            except ProviderFailure as failure:
                self._mark_failure(provider_name, resolved.canonical_symbol, "quote", failure)
                errors.append(failure.to_dict())
            except Exception as exc:
                errors.append(
                    ProviderFailure(
                        str(exc),
                        code=ERROR_PROVIDER_UNAVAILABLE,
                        provider=provider_name,
                        details={"symbol": resolved.canonical_symbol},
                    ).to_dict()
                )

        if local_quote:
            return {**local_quote, "fallback": "stale_local_quote", "errors": errors}

        raise ProviderFailure(
            f"Unable to fetch quote for {resolved.canonical_symbol}",
            code=ERROR_ALL_PROVIDERS_FAILED,
            details={"symbol": resolved.canonical_symbol, "errors": errors},
        )

    def get_market_status(self, exchange: str = "NSE") -> dict[str, Any]:
        return self.nse.get_market_status(exchange)

    def provider_status(self) -> dict[str, Any]:
        providers = []
        for provider in [self.yahoo, self.twelve, self.nse, self.kite]:
            providers.append(
                {
                    "provider": provider.name,
                    "provider_cooldown_remaining_s": round(self._provider_cooldown_remaining(provider.name), 3),
                }
            )

        readiness = self.store.readiness()
        return {
            "providers": providers,
            "store": readiness,
            "timestamp": self._utc_now().isoformat(),
        }

    def job_backfill_historical_data(
        self,
        symbols: list[str],
        years: int = 3,
        interval: str = "1d",
        min_rows: int = 120,
    ) -> dict[str, Any]:
        end = self._utc_now().date()
        start = (end - timedelta(days=365 * max(1, int(years)))).isoformat()

        results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                results.append(
                    self.fetch_historical(
                        symbol=symbol,
                        start_date=start,
                        end_date=end.isoformat(),
                        interval=interval,
                        min_rows=min_rows,
                        force=False,
                    )
                )
            except ProviderFailure as failure:
                results.append(
                    {
                        "status": "failed",
                        "symbol": self.resolver.resolve(symbol).canonical_symbol,
                        "reason": failure.code,
                        "details": failure.details,
                    }
                )

        ok = sum(1 for row in results if row.get("status") == "ok")
        return {
            "job": "backfill_historical_data",
            "status": "ok" if ok == len(results) else "partial",
            "requested": len(symbols),
            "successful": ok,
            "failed": len(results) - ok,
            "results": results,
        }

    def job_refresh_latest_daily_bars(self, symbols: list[str], lookback_days: int = 45) -> dict[str, Any]:
        end = self._utc_now().date().isoformat()
        start = (self._utc_now().date() - timedelta(days=max(10, int(lookback_days)))).isoformat()
        results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                outcome = self.fetch_historical(
                    symbol=symbol,
                    start_date=start,
                    end_date=end,
                    interval="1d",
                    min_rows=5,
                    force=True,
                )
                results.append(outcome)
                # Also export to CSV so PriceFeed (which reads CSVs) stays in sync
                # Use full 2-year range for CSV export (not just lookback window)
                if outcome.get("status") == "ok":
                    try:
                        from pathlib import Path as _Path
                        from .local_access import LocalMarketDataAccess
                        _csv_dir = _Path(__file__).resolve().parents[2] / "storage" / "raw"
                        access = LocalMarketDataAccess()
                        canonical = outcome.get("symbol", symbol)
                        csv_start = (self._utc_now().date() - timedelta(days=730)).isoformat()
                        access.export_symbol_to_csv(
                            symbol=canonical,
                            data_dir=_csv_dir,
                            start_date=csv_start,
                            end_date=end,
                            interval="1d",
                            min_rows=5,
                        )
                    except Exception as csv_exc:
                        logger.warning("CSV export failed for %s: %s", symbol, csv_exc)
            except ProviderFailure as failure:
                results.append(
                    {
                        "status": "failed",
                        "symbol": self.resolver.resolve(symbol).canonical_symbol,
                        "reason": failure.code,
                        "details": failure.details,
                    }
                )
        ok = sum(1 for row in results if row.get("status") == "ok")
        return {
            "job": "refresh_latest_daily_bars",
            "status": "ok" if ok == len(results) else "partial",
            "requested": len(symbols),
            "successful": ok,
            "failed": len(results) - ok,
            "results": results,
        }

    def job_retry_failed_symbols(self, interval: str = "1d", limit: int = 100) -> dict[str, Any]:
        symbols = self.store.get_retry_candidates(interval=interval, limit=limit)
        if not symbols:
            return {"job": "retry_failed_symbols", "status": "ok", "requested": 0, "results": []}
        eligible, dropped = self._filter_retry_candidates(symbols, interval)
        if not eligible:
            return {
                "job": "retry_failed_symbols",
                "status": "ok",
                "requested": 0,
                "dropped_unknown_symbols": dropped,
                "results": [],
            }
        out = self.job_backfill_historical_data(symbols=eligible, years=2, interval=interval, min_rows=30)
        out["dropped_unknown_symbols"] = dropped
        return out

    def job_refresh_metadata(self) -> dict[str, Any]:
        metadata = self.nse.index_metadata()
        self.cache.set_json("metadata:index", metadata, ttl_s=300)
        return {
            "job": "refresh_metadata",
            "status": "ok",
            "metadata": metadata,
        }

    def status(self) -> dict[str, Any]:
        counts = self.store.symbol_row_counts(interval="1d")
        return {
            "service": "market-data",
            "symbols": len(counts),
            "rows": int(sum(counts.values())),
            "top_symbols": [
                {"symbol": sym, "rows": rows}
                for sym, rows in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
            ],
            "provider_status": self.provider_status(),
            "timestamp": self._utc_now().isoformat(),
        }
