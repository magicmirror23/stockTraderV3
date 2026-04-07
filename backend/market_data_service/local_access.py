"""Read-only helper for consumers that must use locally stored market data only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .storage import MarketDataStore
from .symbols import SymbolResolver


@dataclass(frozen=True)
class HydrationResult:
    symbol: str
    rows: int
    csv_path: str | None
    status: str
    reason: str | None = None


class LocalMarketDataAccess:
    """Materialize DB-stored bars into CSVs for legacy feature readers."""

    def __init__(self) -> None:
        self.store = MarketDataStore()
        self.store.ensure_schema()
        self.resolver = SymbolResolver()

    def export_symbol_to_csv(
        self,
        *,
        symbol: str,
        data_dir: str | Path,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        min_rows: int = 1,
    ) -> HydrationResult:
        resolved = self.resolver.resolve(symbol).canonical_symbol
        frame = self.store.query_bars(
            symbol=resolved,
            start=start_date,
            end=end_date,
            interval=interval,
        )
        if len(frame) < max(1, int(min_rows)):
            return HydrationResult(
                symbol=resolved,
                rows=int(len(frame)),
                csv_path=None,
                status="missing",
                reason=f"insufficient_rows:{len(frame)}",
            )

        out = frame.rename(
            columns={
                "timestamp": "Date",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
        )[["Date", "Open", "High", "Low", "Close", "Volume"]]

        target_dir = Path(data_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        csv_path = target_dir / f"{resolved}.csv"
        out.to_csv(csv_path, index=False)
        return HydrationResult(
            symbol=resolved,
            rows=int(len(out)),
            csv_path=str(csv_path),
            status="ok",
        )

    def hydrate_symbols_to_csv(
        self,
        symbols: list[str],
        *,
        data_dir: str | Path,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        min_rows: int = 1,
    ) -> list[HydrationResult]:
        results: list[HydrationResult] = []
        for symbol in symbols:
            results.append(
                self.export_symbol_to_csv(
                    symbol=symbol,
                    data_dir=data_dir,
                    start_date=start_date,
                    end_date=end_date,
                    interval=interval,
                    min_rows=min_rows,
                )
            )
        return results

    def symbol_counts(self, interval: str = "1d") -> dict[str, int]:
        return self.store.symbol_row_counts(interval=interval)

    def available_symbols(self, interval: str = "1d") -> list[str]:
        return self.store.list_symbols(interval=interval)
