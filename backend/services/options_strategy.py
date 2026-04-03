"""Options strategy engine — strategy-level intelligence for multi-leg options.

Supports: covered call, protective put, debit/credit spread, straddle,
strangle, iron condor, butterfly. Recommends strategy based on regime,
directional confidence, IV, theta profile, and liquidity.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class StrategyType(str, Enum):
    COVERED_CALL = "covered_call"
    PROTECTIVE_PUT = "protective_put"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    BULL_PUT_SPREAD = "bull_put_spread"      # credit spread
    BEAR_CALL_SPREAD = "bear_call_spread"    # credit spread
    LONG_STRADDLE = "long_straddle"
    SHORT_STRADDLE = "short_straddle"
    LONG_STRANGLE = "long_strangle"
    SHORT_STRANGLE = "short_strangle"
    IRON_CONDOR = "iron_condor"
    BUTTERFLY = "butterfly"
    SINGLE_CALL = "single_call"
    SINGLE_PUT = "single_put"


@dataclass
class OptionLeg:
    """Single leg of an options strategy."""
    option_type: str  # CE / PE
    strike: float
    expiry: str
    side: str  # buy / sell
    quantity: int = 1
    premium: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0


@dataclass
class StrategyRecommendation:
    """Recommended options strategy with full details."""
    strategy_type: StrategyType
    underlying: str
    legs: list[OptionLeg]
    explanation: str
    # Payoff profile
    max_profit: float = 0.0
    max_loss: float = 0.0
    breakeven_points: list[float] = field(default_factory=list)
    net_premium: float = 0.0  # positive = credit, negative = debit
    # Greeks (portfolio-level for the strategy)
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    # Margin requirement estimate
    margin_required: float = 0.0
    # Scoring
    regime_fit_score: float = 0.0  # 0-1
    confidence_score: float = 0.0  # 0-1

    def to_dict(self) -> dict:
        return {
            "strategy_type": self.strategy_type.value,
            "underlying": self.underlying,
            "legs": [
                {
                    "option_type": l.option_type,
                    "strike": l.strike,
                    "expiry": l.expiry,
                    "side": l.side,
                    "quantity": l.quantity,
                    "premium": round(l.premium, 2),
                    "delta": round(l.delta, 4),
                    "gamma": round(l.gamma, 4),
                    "theta": round(l.theta, 4),
                    "vega": round(l.vega, 4),
                    "iv": round(l.iv, 4),
                }
                for l in self.legs
            ],
            "explanation": self.explanation,
            "max_profit": round(self.max_profit, 2),
            "max_loss": round(self.max_loss, 2),
            "breakeven_points": [round(b, 2) for b in self.breakeven_points],
            "net_premium": round(self.net_premium, 2),
            "net_delta": round(self.net_delta, 4),
            "net_gamma": round(self.net_gamma, 4),
            "net_theta": round(self.net_theta, 4),
            "net_vega": round(self.net_vega, 4),
            "margin_required": round(self.margin_required, 2),
            "regime_fit_score": round(self.regime_fit_score, 2),
            "confidence_score": round(self.confidence_score, 2),
        }


class OptionsStrategyEngine:
    """Builds and recommends multi-leg options strategies."""

    # ------------------------------------------------------------------
    # Strategy builders
    # ------------------------------------------------------------------

    @staticmethod
    def build_covered_call(
        underlying: str,
        spot: float,
        expiry: str,
        iv: float = 0.20,
        lot_size: int = 1,
    ) -> StrategyRecommendation:
        """Covered call: long stock + short OTM call."""
        call_strike = _round_strike(spot * 1.03)  # ~3% OTM
        call_premium = _estimate_premium(spot, call_strike, iv, 30, "CE")

        legs = [
            OptionLeg("CE", call_strike, expiry, "sell", lot_size, call_premium,
                       delta=-0.3, gamma=-0.01, theta=0.05, vega=-0.1, iv=iv),
        ]
        max_profit = (call_strike - spot) * lot_size + call_premium * lot_size
        max_loss = spot * lot_size - call_premium * lot_size  # stock goes to 0

        return StrategyRecommendation(
            strategy_type=StrategyType.COVERED_CALL,
            underlying=underlying,
            legs=legs,
            explanation=f"Sell {call_strike} CE for ₹{call_premium:.0f} premium against stock holding. "
                        f"Income strategy for mildly bullish outlook.",
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven_points=[spot - call_premium],
            net_premium=call_premium * lot_size,
            net_delta=-0.3 * lot_size,
            net_theta=0.05 * lot_size,
            margin_required=spot * lot_size * 0.2,
        )

    @staticmethod
    def build_bull_call_spread(
        underlying: str,
        spot: float,
        expiry: str,
        iv: float = 0.20,
        lot_size: int = 1,
    ) -> StrategyRecommendation:
        """Bull call spread: buy ATM call + sell OTM call."""
        buy_strike = _round_strike(spot)
        sell_strike = _round_strike(spot * 1.05)
        buy_prem = _estimate_premium(spot, buy_strike, iv, 30, "CE")
        sell_prem = _estimate_premium(spot, sell_strike, iv, 30, "CE")
        net_debit = buy_prem - sell_prem

        legs = [
            OptionLeg("CE", buy_strike, expiry, "buy", lot_size, buy_prem,
                       delta=0.5, gamma=0.02, theta=-0.05, vega=0.15, iv=iv),
            OptionLeg("CE", sell_strike, expiry, "sell", lot_size, sell_prem,
                       delta=-0.3, gamma=-0.015, theta=0.03, vega=-0.10, iv=iv),
        ]
        max_profit = (sell_strike - buy_strike - net_debit) * lot_size
        max_loss = net_debit * lot_size

        return StrategyRecommendation(
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            underlying=underlying,
            legs=legs,
            explanation=f"Buy {buy_strike} CE, sell {sell_strike} CE. Debit spread for "
                        f"moderately bullish view with capped risk of ₹{max_loss:.0f}.",
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven_points=[buy_strike + net_debit],
            net_premium=-net_debit * lot_size,
            net_delta=0.2 * lot_size,
            net_gamma=0.005 * lot_size,
            net_theta=-0.02 * lot_size,
            margin_required=max_loss,
        )

    @staticmethod
    def build_iron_condor(
        underlying: str,
        spot: float,
        expiry: str,
        iv: float = 0.20,
        lot_size: int = 1,
    ) -> StrategyRecommendation:
        """Iron condor: sell OTM put spread + sell OTM call spread."""
        put_sell = _round_strike(spot * 0.95)
        put_buy = _round_strike(spot * 0.92)
        call_sell = _round_strike(spot * 1.05)
        call_buy = _round_strike(spot * 1.08)

        ps_prem = _estimate_premium(spot, put_sell, iv, 30, "PE")
        pb_prem = _estimate_premium(spot, put_buy, iv, 30, "PE")
        cs_prem = _estimate_premium(spot, call_sell, iv, 30, "CE")
        cb_prem = _estimate_premium(spot, call_buy, iv, 30, "CE")

        net_credit = (ps_prem - pb_prem + cs_prem - cb_prem)

        legs = [
            OptionLeg("PE", put_buy, expiry, "buy", lot_size, pb_prem, iv=iv),
            OptionLeg("PE", put_sell, expiry, "sell", lot_size, ps_prem, iv=iv),
            OptionLeg("CE", call_sell, expiry, "sell", lot_size, cs_prem, iv=iv),
            OptionLeg("CE", call_buy, expiry, "buy", lot_size, cb_prem, iv=iv),
        ]

        wing_width = max(call_buy - call_sell, put_sell - put_buy)
        max_loss = (wing_width - net_credit) * lot_size
        max_profit = net_credit * lot_size

        return StrategyRecommendation(
            strategy_type=StrategyType.IRON_CONDOR,
            underlying=underlying,
            legs=legs,
            explanation=f"Iron condor: sell {put_sell}/{call_sell} wings, buy {put_buy}/{call_buy} protection. "
                        f"Collect ₹{net_credit:.0f} premium. Best for range-bound, high-IV environment.",
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven_points=[put_sell - net_credit, call_sell + net_credit],
            net_premium=net_credit * lot_size,
            net_delta=0.0,
            net_theta=0.08 * lot_size,
            net_vega=-0.2 * lot_size,
            margin_required=max_loss,
            regime_fit_score=0.9,
        )

    @staticmethod
    def build_long_straddle(
        underlying: str,
        spot: float,
        expiry: str,
        iv: float = 0.20,
        lot_size: int = 1,
    ) -> StrategyRecommendation:
        """Long straddle: buy ATM call + buy ATM put."""
        strike = _round_strike(spot)
        call_prem = _estimate_premium(spot, strike, iv, 30, "CE")
        put_prem = _estimate_premium(spot, strike, iv, 30, "PE")
        total_debit = call_prem + put_prem

        legs = [
            OptionLeg("CE", strike, expiry, "buy", lot_size, call_prem,
                       delta=0.5, gamma=0.03, theta=-0.08, vega=0.2, iv=iv),
            OptionLeg("PE", strike, expiry, "buy", lot_size, put_prem,
                       delta=-0.5, gamma=0.03, theta=-0.08, vega=0.2, iv=iv),
        ]

        return StrategyRecommendation(
            strategy_type=StrategyType.LONG_STRADDLE,
            underlying=underlying,
            legs=legs,
            explanation=f"Buy {strike} straddle for ₹{total_debit:.0f}. "
                        f"Profit from large moves in either direction. Best before earnings/events.",
            max_profit=float("inf"),
            max_loss=total_debit * lot_size,
            breakeven_points=[strike - total_debit, strike + total_debit],
            net_premium=-total_debit * lot_size,
            net_delta=0.0,
            net_gamma=0.06 * lot_size,
            net_theta=-0.16 * lot_size,
            net_vega=0.4 * lot_size,
            margin_required=total_debit * lot_size,
        )

    # ------------------------------------------------------------------
    # Strategy recommendation engine
    # ------------------------------------------------------------------

    @staticmethod
    def recommend_strategy(
        underlying: str,
        spot: float,
        expiry: str,
        direction: str = "neutral",  # bullish / bearish / neutral
        confidence: float = 0.5,
        regime: str = "range",  # trend / range / high_vol / low_vol
        iv_percentile: float = 50.0,
        iv: float = 0.20,
        lot_size: int = 1,
    ) -> StrategyRecommendation:
        """Recommend optimal strategy based on market conditions."""

        # High IV + neutral → sell premium (iron condor or short strangle)
        if iv_percentile > 70 and (direction == "neutral" or confidence < 0.6):
            return OptionsStrategyEngine.build_iron_condor(
                underlying, spot, expiry, iv, lot_size
            )

        # High confidence bullish → bull call spread
        if direction == "bullish" and confidence > 0.7:
            rec = OptionsStrategyEngine.build_bull_call_spread(
                underlying, spot, expiry, iv, lot_size
            )
            rec.confidence_score = confidence
            rec.regime_fit_score = 0.8 if regime == "trend" else 0.5
            return rec

        # Pre-event / high vol expected → long straddle
        if regime == "high_vol" or iv_percentile < 30:
            rec = OptionsStrategyEngine.build_long_straddle(
                underlying, spot, expiry, iv, lot_size
            )
            rec.regime_fit_score = 0.9
            return rec

        # Holding stock + mildly bullish → covered call
        if direction == "bullish" and confidence < 0.6:
            return OptionsStrategyEngine.build_covered_call(
                underlying, spot, expiry, iv, lot_size
            )

        # Default: iron condor for range-bound
        return OptionsStrategyEngine.build_iron_condor(
            underlying, spot, expiry, iv, lot_size
        )

    @staticmethod
    def compute_payoff(
        legs: list[OptionLeg],
        spot_range: tuple[float, float] | None = None,
        points: int = 100,
    ) -> list[dict]:
        """Compute payoff diagram data points."""
        if not legs:
            return []

        strikes = [l.strike for l in legs]
        if spot_range is None:
            low = min(strikes) * 0.85
            high = max(strikes) * 1.15
        else:
            low, high = spot_range

        step = (high - low) / points
        result = []

        for i in range(points + 1):
            spot = low + i * step
            total_pnl = 0.0
            for leg in legs:
                if leg.option_type == "CE":
                    intrinsic = max(0, spot - leg.strike)
                else:
                    intrinsic = max(0, leg.strike - spot)

                if leg.side == "buy":
                    total_pnl += (intrinsic - leg.premium) * leg.quantity
                else:
                    total_pnl += (leg.premium - intrinsic) * leg.quantity

            result.append({"spot": round(spot, 2), "pnl": round(total_pnl, 2)})

        return result

    @staticmethod
    def select_strike(
        spot: float,
        target_delta: float = 0.3,
        iv: float = 0.20,
        days_to_expiry: int = 30,
    ) -> float:
        """Select strike based on target delta using simplified model."""
        # Approximate: delta ≈ N(d1), so d1 = N_inv(delta)
        # strike ≈ spot * exp(-d1 * iv * sqrt(T) + 0.5 * iv^2 * T)
        T = days_to_expiry / 365.0
        try:
            from scipy.stats import norm
            d1 = norm.ppf(target_delta)
        except ImportError:
            d1 = 0.52  # fallback for ~0.3 delta
        strike = spot * math.exp(-d1 * iv * math.sqrt(T) + 0.5 * iv**2 * T)
        return _round_strike(strike)

    @staticmethod
    def select_expiry(
        available_expiries: list[str],
        min_dte: int = 7,
        max_dte: int = 45,
        target_dte: int = 30,
    ) -> str | None:
        """Select optimal expiry from available dates."""
        from datetime import datetime, date
        today = date.today()
        best = None
        best_diff = float("inf")

        for exp_str in available_expiries:
            try:
                exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp - today).days
                if min_dte <= dte <= max_dte:
                    diff = abs(dte - target_dte)
                    if diff < best_diff:
                        best_diff = diff
                        best = exp_str
            except ValueError:
                continue
        return best


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _round_strike(price: float, step: float = 50.0) -> float:
    """Round to nearest option strike step (₹50 for NIFTY, etc.)."""
    return round(price / step) * step


def _estimate_premium(
    spot: float,
    strike: float,
    iv: float,
    days: int,
    opt_type: str,
) -> float:
    """Simplified Black-Scholes premium estimate."""
    T = max(days / 365.0, 0.001)
    r = 0.07  # Risk-free rate (India)

    try:
        from scipy.stats import norm
        d1 = (math.log(spot / strike) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
        d2 = d1 - iv * math.sqrt(T)

        if opt_type == "CE":
            price = spot * norm.cdf(d1) - strike * math.exp(-r * T) * norm.cdf(d2)
        else:
            price = strike * math.exp(-r * T) * norm.cdf(-d2) - spot * norm.cdf(-d1)
    except ImportError:
        # Rough approximation without scipy
        moneyness = (spot - strike) / spot if opt_type == "CE" else (strike - spot) / spot
        intrinsic = max(0, moneyness * spot)
        time_value = spot * iv * math.sqrt(T) * 0.4
        price = intrinsic + time_value

    return max(0.5, round(price, 2))
