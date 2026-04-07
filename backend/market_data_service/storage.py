"""Persistence layer for canonical market bars and provider failure state."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.db.models import MarketBar, MarketDataFailure
from backend.db.session import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


class MarketDataStore:
    """Store and query normalized OHLCV bars."""

    def __init__(self) -> None:
        self._parquet_enabled = os.getenv("MARKET_DATA_PARQUET_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "y",
        }
        self._parquet_root = Path(
            os.getenv(
                "MARKET_DATA_PARQUET_ROOT",
                str(Path(__file__).resolve().parents[2] / "storage" / "parquet" / "ohlcv"),
            )
        )

    @staticmethod
    def ensure_schema() -> None:
        Base.metadata.create_all(bind=engine)

    @staticmethod
    def _frame_payload(df: pd.DataFrame) -> list[dict]:
        payload: list[dict] = []
        now = datetime.now(timezone.utc)
        for row in df.itertuples(index=False):
            payload.append(
                {
                    "symbol": str(row.symbol),
                    "timestamp": pd.Timestamp(row.timestamp).to_pydatetime(),
                    "interval": str(row.interval),
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume or 0.0),
                    "source": str(row.source),
                    "ingested_at": now,
                }
            )
        return payload

    def upsert_bars(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        payload = self._frame_payload(df)
        inserted = 0

        with SessionLocal() as db:
            dialect = db.bind.dialect.name
            if dialect == "postgresql":
                stmt = pg_insert(MarketBar).values(payload)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol", "timestamp", "interval"],
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                        "source": stmt.excluded.source,
                        "ingested_at": stmt.excluded.ingested_at,
                    },
                )
                result = db.execute(stmt)
                inserted = int(result.rowcount or 0)
            else:
                stmt = sqlite_insert(MarketBar).values(payload)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol", "timestamp", "interval"],
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                        "source": stmt.excluded.source,
                        "ingested_at": stmt.excluded.ingested_at,
                    },
                )
                result = db.execute(stmt)
                inserted = int(result.rowcount or 0)

            db.commit()

        self._persist_parquet(df)
        return inserted

    def _persist_parquet(self, df: pd.DataFrame) -> None:
        if not self._parquet_enabled or df.empty:
            return

        try:
            for symbol, symbol_df in df.groupby("symbol"):
                for interval, interval_df in symbol_df.groupby("interval"):
                    out_dir = self._parquet_root / f"interval={interval}" / f"symbol={symbol}"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_path = out_dir / "bars.parquet"
                    if out_path.exists():
                        old = pd.read_parquet(out_path)
                        merged = pd.concat([old, interval_df], ignore_index=True)
                        merged = merged.drop_duplicates(subset=["timestamp", "symbol", "interval"], keep="last")
                        merged = merged.sort_values("timestamp")
                    else:
                        merged = interval_df.sort_values("timestamp")
                    merged.to_parquet(out_path, index=False)
        except Exception as exc:
            logger.warning("Parquet persistence skipped: %s", exc)

    def query_bars(
        self,
        symbol: str,
        start: datetime | str,
        end: datetime | str,
        interval: str = "1d",
        limit: int | None = None,
    ) -> pd.DataFrame:
        start_ts = pd.Timestamp(start).to_pydatetime()
        end_ts = pd.Timestamp(end).to_pydatetime()

        with SessionLocal() as db:
            stmt = (
                select(
                    MarketBar.timestamp,
                    MarketBar.open,
                    MarketBar.high,
                    MarketBar.low,
                    MarketBar.close,
                    MarketBar.volume,
                    MarketBar.symbol,
                    MarketBar.interval,
                    MarketBar.source,
                )
                .where(MarketBar.symbol == symbol)
                .where(MarketBar.interval == interval)
                .where(MarketBar.timestamp >= start_ts)
                .where(MarketBar.timestamp <= end_ts)
                .order_by(MarketBar.timestamp.asc())
            )
            if limit is not None:
                stmt = stmt.limit(int(limit))
            rows = db.execute(stmt).all()

        if not rows:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol", "interval", "source"])
        return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "symbol", "interval", "source"])

    def latest_quote(self, symbol: str, interval: str = "1d") -> dict | None:
        with SessionLocal() as db:
            latest = (
                db.query(MarketBar)
                .filter(MarketBar.symbol == symbol)
                .filter(MarketBar.interval == interval)
                .order_by(MarketBar.timestamp.desc())
                .first()
            )
            prev = (
                db.query(MarketBar)
                .filter(MarketBar.symbol == symbol)
                .filter(MarketBar.interval == interval)
                .order_by(MarketBar.timestamp.desc())
                .offset(1)
                .first()
            )

        if latest is None:
            return None

        prev_close = float(prev.close) if prev is not None else float(latest.close)
        change = float(latest.close) - prev_close
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0
        return {
            "symbol": latest.symbol,
            "price": float(latest.close),
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "timestamp": latest.timestamp.isoformat(),
            "provider": latest.source,
        }

    def symbol_row_counts(self, interval: str = "1d") -> dict[str, int]:
        with SessionLocal() as db:
            rows = (
                db.query(MarketBar.symbol, func.count(MarketBar.id))
                .filter(MarketBar.interval == interval)
                .group_by(MarketBar.symbol)
                .all()
            )
        return {str(symbol): int(count) for symbol, count in rows}

    def list_symbols(self, interval: str = "1d") -> list[str]:
        return sorted(self.symbol_row_counts(interval=interval).keys())

    def save_failure(
        self,
        *,
        symbol: str,
        interval: str,
        provider: str,
        error_code: str,
        message: str,
        cooldown_seconds: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        cooldown_until = now + timedelta(seconds=max(1, int(cooldown_seconds)))

        with SessionLocal() as db:
            existing = (
                db.query(MarketDataFailure)
                .filter(and_(MarketDataFailure.symbol == symbol, MarketDataFailure.interval == interval))
                .first()
            )
            if existing:
                existing.provider = provider
                existing.error_code = error_code
                existing.last_error = message
                existing.last_attempt_at = now
                existing.cooldown_until = cooldown_until
                existing.attempts = int(existing.attempts or 0) + 1
            else:
                db.add(
                    MarketDataFailure(
                        symbol=symbol,
                        interval=interval,
                        provider=provider,
                        error_code=error_code,
                        last_error=message,
                        attempts=1,
                        last_attempt_at=now,
                        cooldown_until=cooldown_until,
                    )
                )
            db.commit()

    def clear_failure(self, symbol: str, interval: str) -> None:
        with SessionLocal() as db:
            db.query(MarketDataFailure).filter(
                and_(MarketDataFailure.symbol == symbol, MarketDataFailure.interval == interval)
            ).delete()
            db.commit()

    def get_retry_candidates(self, interval: str = "1d", limit: int = 100) -> list[str]:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            rows = (
                db.query(MarketDataFailure.symbol)
                .filter(MarketDataFailure.interval == interval)
                .filter(MarketDataFailure.cooldown_until <= now)
                .order_by(MarketDataFailure.last_attempt_at.asc())
                .limit(int(limit))
                .all()
            )
        return [str(r[0]) for r in rows]

    def failure_attempt_counts(
        self,
        *,
        symbols: list[str] | None = None,
        interval: str = "1d",
    ) -> dict[str, int]:
        with SessionLocal() as db:
            query = (
                db.query(MarketDataFailure.symbol, MarketDataFailure.attempts)
                .filter(MarketDataFailure.interval == interval)
            )
            if symbols:
                query = query.filter(MarketDataFailure.symbol.in_(symbols))
            rows = query.all()
        return {str(symbol): int(attempts or 0) for symbol, attempts in rows}

    def readiness(self) -> dict[str, int | bool]:
        counts = self.symbol_row_counts()
        return {
            "has_data": bool(counts),
            "symbols": len(counts),
            "rows": int(sum(counts.values())),
        }
