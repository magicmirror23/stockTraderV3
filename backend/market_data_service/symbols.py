"""Centralized symbol normalization and provider-specific symbol mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedSymbol:
    input_symbol: str
    canonical_symbol: str
    yahoo_symbol: str
    twelve_data_symbol: str
    exchange: str
    is_index: bool


class SymbolResolver:
    """Resolve internal symbols to provider-specific formats."""

    INDEX_YAHOO_MAP: dict[str, str] = {
        "NIFTY50": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "SENSEX": "^BSESN",
    }

    INDEX_TWELVE_MAP: dict[str, str] = {
        "NIFTY50": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "SENSEX": "SENSEX",
    }

    SYMBOL_OVERRIDES: dict[str, str] = {
        "BAJAJ_AUTO": "BAJAJ-AUTO",
        "M_M": "M&M",
    }

    def normalize(self, symbol: str) -> str:
        if not symbol:
            return ""
        out = str(symbol).strip().upper()

        # Strip common exchange suffixes first.
        if out.endswith(".NS") or out.endswith(".BO"):
            out = out[:-3]

        # Convert separators back to canonical underscore style internally.
        out = out.replace("-", "_")
        out = out.replace("&", "_")
        out = "_".join(part for part in out.split("_") if part)
        return out

    def is_index(self, symbol: str) -> bool:
        return self.normalize(symbol) in self.INDEX_YAHOO_MAP

    def to_yahoo(self, symbol: str) -> str:
        canonical = self.normalize(symbol)
        if canonical in self.INDEX_YAHOO_MAP:
            return self.INDEX_YAHOO_MAP[canonical]

        mapped = self.SYMBOL_OVERRIDES.get(canonical, canonical)
        if "_" in mapped:
            parts = [p for p in mapped.split("_") if p]
            if all(len(p) == 1 for p in parts):
                mapped = "&".join(parts)
            else:
                mapped = "-".join(parts)
        return f"{mapped}.NS"

    def to_twelve_data(self, symbol: str) -> str:
        canonical = self.normalize(symbol)
        if canonical in self.INDEX_TWELVE_MAP:
            return self.INDEX_TWELVE_MAP[canonical]

        mapped = self.SYMBOL_OVERRIDES.get(canonical, canonical)
        mapped = mapped.replace("_", "-")
        return f"{mapped}:NSE"

    def resolve(self, symbol: str) -> ResolvedSymbol:
        canonical = self.normalize(symbol)
        is_index = canonical in self.INDEX_YAHOO_MAP
        exchange = "NSE" if not is_index else "INDEX"
        return ResolvedSymbol(
            input_symbol=str(symbol),
            canonical_symbol=canonical,
            yahoo_symbol=self.to_yahoo(canonical),
            twelve_data_symbol=self.to_twelve_data(canonical),
            exchange=exchange,
            is_index=is_index,
        )
