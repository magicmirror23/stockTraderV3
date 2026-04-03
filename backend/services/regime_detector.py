"""Market regime detector — classifies current market conditions.

Regimes: TRENDING_UP, TRENDING_DOWN, RANGE_BOUND, HIGH_VOLATILITY,
         LOW_VOLATILITY, GAP_UP, GAP_DOWN, CRASH
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE_BOUND = "range_bound"
    HIGH_VOLATILITY = "high_vol"
    LOW_VOLATILITY = "low_vol"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"
    CRASH = "crash"
    UNKNOWN = "unknown"


@dataclass
class RegimeResult:
    """Result of regime detection for a symbol or index."""
    regime: MarketRegime
    confidence: float  # 0-1
    volatility: float  # annualized
    trend_strength: float  # -1 (strong down) to +1 (strong up)
    atr_pct: float  # ATR as % of price
    volume_ratio: float  # current vs average
    details: dict

    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "confidence": round(self.confidence, 3),
            "volatility": round(self.volatility, 4),
            "trend_strength": round(self.trend_strength, 3),
            "atr_pct": round(self.atr_pct, 4),
            "volume_ratio": round(self.volume_ratio, 2),
            "details": self.details,
        }


class RegimeDetector:
    """Detect market regime from price data.

    Uses a combination of:
    - Rolling volatility (20-day std of returns, annualized)
    - Trend (20-day SMA slope + ADX-like strength)
    - Range detection (Bollinger bandwidth)
    - Gap detection (open vs previous close)
    - Volume regime (current vs 20-day average)
    """

    def __init__(self, lookback: int = 60, vol_window: int = 20) -> None:
        self.lookback = lookback
        self.vol_window = vol_window
        self._cache: dict[str, RegimeResult] = {}

    def detect(self, df: pd.DataFrame, symbol: str = "") -> RegimeResult:
        """Detect regime from OHLCV DataFrame.

        Args:
            df: DataFrame with columns [open, high, low, close, volume].
                Must have at least `lookback` rows.
            symbol: optional ticker for caching.

        Returns:
            RegimeResult
        """
        if df is None or len(df) < self.vol_window + 5:
            return RegimeResult(
                regime=MarketRegime.UNKNOWN, confidence=0, volatility=0,
                trend_strength=0, atr_pct=0, volume_ratio=1, details={},
            )

        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        volume = df["volume"].values.astype(float) if "volume" in df.columns else np.ones(len(close))
        open_prices = df["open"].values.astype(float) if "open" in df.columns else close

        # Returns
        returns = np.diff(close) / close[:-1]
        recent_returns = returns[-self.vol_window:]

        # Volatility (annualized)
        vol = float(np.std(recent_returns) * np.sqrt(252))

        # ATR
        tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
        tr = np.maximum(tr, np.abs(low[1:] - close[:-1]))
        atr = float(np.mean(tr[-self.vol_window:]))
        atr_pct = atr / close[-1] if close[-1] > 0 else 0

        # Trend: SMA slope
        sma_short = float(np.mean(close[-10:]))
        sma_long = float(np.mean(close[-self.vol_window:]))
        trend_strength = (sma_short - sma_long) / sma_long if sma_long > 0 else 0

        # Volume ratio
        avg_vol = float(np.mean(volume[-self.vol_window:])) if len(volume) >= self.vol_window else 1
        current_vol = float(volume[-1]) if len(volume) > 0 else 1
        volume_ratio = current_vol / avg_vol if avg_vol > 0 else 1

        # Gap detection
        gap_pct = (open_prices[-1] - close[-2]) / close[-2] if len(close) >= 2 and close[-2] > 0 else 0

        # Bollinger bandwidth
        bb_mid = np.mean(close[-self.vol_window:])
        bb_std = np.std(close[-self.vol_window:])
        bb_width = (2 * bb_std) / bb_mid if bb_mid > 0 else 0

        # Classify regime
        regime, confidence = self._classify(
            vol, trend_strength, atr_pct, volume_ratio, gap_pct, bb_width, recent_returns
        )

        result = RegimeResult(
            regime=regime,
            confidence=confidence,
            volatility=vol,
            trend_strength=trend_strength,
            atr_pct=atr_pct,
            volume_ratio=volume_ratio,
            details={
                "bb_width": round(bb_width, 4),
                "gap_pct": round(gap_pct, 4),
                "sma_short": round(sma_short, 2),
                "sma_long": round(sma_long, 2),
                "recent_return": round(float(np.sum(recent_returns)), 4),
            },
        )

        if symbol:
            self._cache[symbol] = result
        return result

    def _classify(
        self, vol: float, trend: float, atr_pct: float,
        vol_ratio: float, gap_pct: float, bb_width: float,
        returns: np.ndarray,
    ) -> tuple[MarketRegime, float]:
        """Multi-signal regime classification."""

        # Crash detection (high priority)
        cumulative_return = float(np.sum(returns[-5:])) if len(returns) >= 5 else 0
        if cumulative_return < -0.05 and vol > 0.4:
            return MarketRegime.CRASH, min(0.9, abs(cumulative_return) * 10)

        # Gap detection
        if gap_pct > 0.02:
            return MarketRegime.GAP_UP, min(0.85, gap_pct * 20)
        if gap_pct < -0.02:
            return MarketRegime.GAP_DOWN, min(0.85, abs(gap_pct) * 20)

        # Volatility extremes
        if vol > 0.35:
            return MarketRegime.HIGH_VOLATILITY, min(0.9, vol * 2)
        if vol < 0.10:
            return MarketRegime.LOW_VOLATILITY, min(0.8, (0.15 - vol) * 10)

        # Trend detection
        if trend > 0.02 and bb_width < 0.08:
            conf = min(0.85, abs(trend) * 20)
            return MarketRegime.TRENDING_UP, conf
        if trend < -0.02 and bb_width < 0.08:
            conf = min(0.85, abs(trend) * 20)
            return MarketRegime.TRENDING_DOWN, conf

        # Range bound
        if bb_width < 0.04 and abs(trend) < 0.01:
            return MarketRegime.RANGE_BOUND, min(0.8, (0.05 - bb_width) * 20)

        # Default
        if trend > 0:
            return MarketRegime.TRENDING_UP, 0.5
        elif trend < 0:
            return MarketRegime.TRENDING_DOWN, 0.5
        return MarketRegime.RANGE_BOUND, 0.4

    def detect_for_symbol(self, symbol: str) -> RegimeResult:
        """Load data and detect regime for a specific NSE symbol."""
        try:
            from pathlib import Path
            csv_path = Path(__file__).resolve().parents[2] / "storage" / "raw" / f"{symbol}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                # Normalize column names
                df.columns = [c.lower().strip() for c in df.columns]
                return self.detect(df.tail(self.lookback), symbol)
        except Exception as exc:
            logger.debug("Regime detection from CSV failed for %s: %s", symbol, exc)

        return RegimeResult(
            regime=MarketRegime.UNKNOWN, confidence=0, volatility=0,
            trend_strength=0, atr_pct=0, volume_ratio=1, details={"error": "no_data"},
        )

    def get_market_heatmap(self, symbols: list[str] | None = None) -> dict[str, dict]:
        """Get regime for multiple symbols as a heatmap."""
        if not symbols:
            symbols = [
                "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
                "SBIN", "TATAMOTORS", "MARUTI", "ITC", "HINDUNILVR",
            ]
        result = {}
        for sym in symbols:
            r = self.detect_for_symbol(sym)
            result[sym] = r.to_dict()
        return result

    def get_cached(self, symbol: str) -> RegimeResult | None:
        return self._cache.get(symbol)


_regime_detector: RegimeDetector | None = None


def get_regime_detector() -> RegimeDetector:
    """Module-level singleton accessor."""
    global _regime_detector
    if _regime_detector is None:
        _regime_detector = RegimeDetector()
    return _regime_detector
