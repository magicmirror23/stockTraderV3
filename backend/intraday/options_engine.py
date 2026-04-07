"""Options / F&O signal engine – generates derivatives trading signals
from underlying trend, volatility regime, and option chain features.

Supported signal templates:
  long_call_breakout, long_put_breakdown, bull_call_spread,
  bear_put_spread, no_trade

Initially uses simulated option chain data; can integrate live chain
data when available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class OptionSignalType(str, Enum):
    LONG_CALL_BREAKOUT = "long_call_breakout"
    LONG_PUT_BREAKDOWN = "long_put_breakdown"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    NO_TRADE = "no_trade"


class VolatilityRegime(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class OptionChainSnapshot:
    """Option chain data for a single underlying at a point in time."""

    symbol: str
    underlying_price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Aggregate metrics
    put_call_ratio: float = 1.0
    total_oi_calls: int = 0
    total_oi_puts: int = 0
    oi_change_calls: int = 0
    oi_change_puts: int = 0
    max_pain_strike: float = 0.0

    # IV surface
    atm_iv: float = 0.15
    iv_skew: float = 0.0           # OTM put IV - OTM call IV
    iv_term_structure: float = 0.0  # near-term IV - far-term IV

    # Near-expiry
    days_to_expiry: int = 7
    near_expiry_date: str = ""


@dataclass
class OptionSignal:
    """A generated F&O signal for execution."""

    symbol: str
    signal_type: OptionSignalType
    direction: str                  # "bullish" | "bearish" | "neutral"
    confidence: float               # 0-1
    underlying_price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Recommended strikes / structure
    entry_strike: float = 0.0
    exit_strike: float = 0.0       # for spreads
    option_type: str = "CE"         # "CE" | "PE"
    expiry: str = ""
    lot_size: int = 1

    # Risk parameters
    max_loss: float = 0.0
    max_profit: float = 0.0
    breakeven: float = 0.0
    risk_reward: float = 0.0

    # Context
    volatility_regime: str = "normal"
    reasoning: list[str] = field(default_factory=list)

    eligible: bool = True
    rejection_reason: str = ""


# ── Signal generation rules ───────────────────────────────────────────────


@dataclass
class FnOConfig:
    """Configuration for F&O signal generation."""

    # Thresholds
    min_confidence: float = 0.60
    min_iv_percentile: float = 20.0
    max_iv_percentile: float = 90.0
    min_days_to_expiry: int = 2
    max_days_to_expiry: int = 30
    pcr_bullish_threshold: float = 0.7
    pcr_bearish_threshold: float = 1.3

    # Moneyness
    otm_pct_single: float = 0.02    # 2% OTM for single legs
    otm_pct_spread_near: float = 0.01
    otm_pct_spread_far: float = 0.04

    # Risk
    max_premium_pct: float = 0.02   # max 2% of capital per trade
    prefer_spreads_in_high_iv: bool = True


class OptionSignalEngine:
    """Generates F&O signals based on underlying and option chain analysis."""

    def __init__(self, config: FnOConfig | None = None):
        self.config = config or FnOConfig()

    def classify_volatility(self, atm_iv: float) -> VolatilityRegime:
        """Classify IV into regimes."""
        if atm_iv < 0.12:
            return VolatilityRegime.LOW
        elif atm_iv < 0.22:
            return VolatilityRegime.NORMAL
        elif atm_iv < 0.35:
            return VolatilityRegime.HIGH
        else:
            return VolatilityRegime.EXTREME

    def generate_signal(
        self,
        underlying_trend: str,      # "bullish" | "bearish" | "neutral"
        trend_confidence: float,
        chain: OptionChainSnapshot | None = None,
        intraday_signal: Any | None = None,
    ) -> OptionSignal:
        """Generate an F&O signal from underlying analysis and option chain data.

        Parameters
        ----------
        underlying_trend : str
            Direction of underlying ("bullish", "bearish", "neutral").
        trend_confidence : float
            Confidence in the trend direction (0-1).
        chain : optional
            Option chain snapshot. If None, uses simulated defaults.
        intraday_signal : optional
            The intraday ML signal, if available.
        """
        cfg = self.config

        # Default chain if not provided
        if chain is None:
            chain = OptionChainSnapshot(
                symbol="UNKNOWN", underlying_price=0,
                atm_iv=0.18, put_call_ratio=1.0,
                days_to_expiry=7,
            )

        vol_regime = self.classify_volatility(chain.atm_iv)
        reasons: list[str] = []

        # ── Check eligibility ─────────────────────────────
        if chain.days_to_expiry < cfg.min_days_to_expiry:
            return OptionSignal(
                symbol=chain.symbol, signal_type=OptionSignalType.NO_TRADE,
                direction="neutral", confidence=0, underlying_price=chain.underlying_price,
                eligible=False, rejection_reason="too_close_to_expiry",
                volatility_regime=vol_regime.value,
            )

        if chain.days_to_expiry > cfg.max_days_to_expiry:
            return OptionSignal(
                symbol=chain.symbol, signal_type=OptionSignalType.NO_TRADE,
                direction="neutral", confidence=0, underlying_price=chain.underlying_price,
                eligible=False, rejection_reason="expiry_too_far",
                volatility_regime=vol_regime.value,
            )

        if trend_confidence < cfg.min_confidence:
            return OptionSignal(
                symbol=chain.symbol, signal_type=OptionSignalType.NO_TRADE,
                direction="neutral", confidence=0, underlying_price=chain.underlying_price,
                eligible=False, rejection_reason="low_confidence",
                volatility_regime=vol_regime.value,
            )

        # ── PCR context ───────────────────────────────────
        pcr = chain.put_call_ratio
        pcr_bias = "neutral"
        if pcr < cfg.pcr_bullish_threshold:
            pcr_bias = "bullish"
            reasons.append(f"PCR {pcr:.2f} suggests bullish sentiment")
        elif pcr > cfg.pcr_bearish_threshold:
            pcr_bias = "bearish"
            reasons.append(f"PCR {pcr:.2f} suggests bearish sentiment")

        # ── Signal type selection ─────────────────────────
        use_spread = (
            vol_regime in (VolatilityRegime.HIGH, VolatilityRegime.EXTREME)
            and cfg.prefer_spreads_in_high_iv
        )

        price = chain.underlying_price

        if underlying_trend == "bullish":
            if use_spread:
                sig_type = OptionSignalType.BULL_CALL_SPREAD
                entry_strike = round(price * (1 + cfg.otm_pct_spread_near), -1)
                exit_strike = round(price * (1 + cfg.otm_pct_spread_far), -1)
                option_type = "CE"
                reasons.append("High IV → using spread to limit cost")
            else:
                sig_type = OptionSignalType.LONG_CALL_BREAKOUT
                entry_strike = round(price * (1 + cfg.otm_pct_single), -1)
                exit_strike = 0
                option_type = "CE"
                reasons.append("Bullish breakout → long call")

        elif underlying_trend == "bearish":
            if use_spread:
                sig_type = OptionSignalType.BEAR_PUT_SPREAD
                entry_strike = round(price * (1 - cfg.otm_pct_spread_near), -1)
                exit_strike = round(price * (1 - cfg.otm_pct_spread_far), -1)
                option_type = "PE"
                reasons.append("High IV → using put spread to limit cost")
            else:
                sig_type = OptionSignalType.LONG_PUT_BREAKDOWN
                entry_strike = round(price * (1 - cfg.otm_pct_single), -1)
                exit_strike = 0
                option_type = "PE"
                reasons.append("Bearish breakdown → long put")
        else:
            return OptionSignal(
                symbol=chain.symbol, signal_type=OptionSignalType.NO_TRADE,
                direction="neutral", confidence=0, underlying_price=price,
                eligible=False, rejection_reason="neutral_trend",
                volatility_regime=vol_regime.value, reasoning=reasons,
            )

        # ── Risk parameters (simplified) ──────────────────
        # Rough premium estimate using simplified Black-Scholes-like proxy
        moneyness = abs(entry_strike - price) / price
        time_factor = np.sqrt(chain.days_to_expiry / 365)
        est_premium = price * chain.atm_iv * time_factor * np.exp(-moneyness * 5)

        if use_spread and exit_strike > 0:
            spread_width = abs(exit_strike - entry_strike)
            max_loss = est_premium * 0.6  # net debit estimate
            max_profit = spread_width - max_loss
        else:
            max_loss = est_premium
            max_profit = est_premium * 3  # rough target

        risk_reward = max_profit / max(max_loss, 1) if max_loss > 0 else 0
        breakeven = (
            entry_strike + est_premium if option_type == "CE"
            else entry_strike - est_premium
        )

        direction = "bullish" if underlying_trend == "bullish" else "bearish"

        return OptionSignal(
            symbol=chain.symbol,
            signal_type=sig_type,
            direction=direction,
            confidence=trend_confidence,
            underlying_price=price,
            entry_strike=entry_strike,
            exit_strike=exit_strike,
            option_type=option_type,
            expiry=chain.near_expiry_date,
            max_loss=max_loss,
            max_profit=max_profit,
            breakeven=breakeven,
            risk_reward=risk_reward,
            volatility_regime=vol_regime.value,
            reasoning=reasons,
        )

    def generate_signals_batch(
        self,
        signals: list[dict[str, Any]],
    ) -> list[OptionSignal]:
        """Generate F&O signals for multiple underlyings."""
        results = []
        for s in signals:
            result = self.generate_signal(
                underlying_trend=s.get("trend", "neutral"),
                trend_confidence=s.get("confidence", 0),
                chain=s.get("chain"),
                intraday_signal=s.get("intraday_signal"),
            )
            results.append(result)
        return results
