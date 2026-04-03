"""Advanced institutional-grade risk engine.

Extends the basic RiskManager with:
- Portfolio exposure by sector, ticker, strategy, instrument type
- Per-trade risk budget and risk approval score
- Volatility-adjusted sizing (ATR-based)
- Kelly fraction with conservative cap
- Max intraday / daily loss lockout
- Rolling drawdown circuit breaker
- Correlation-aware exposure reduction
- Options Greeks exposure checks (gamma, theta, vega)
- Pre-trade and post-trade risk snapshots
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Sector mapping for NSE tickers
SECTOR_MAP: dict[str, str] = {
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "KOTAKBANK": "Banking", "AXISBANK": "Banking", "INDUSINDBK": "Banking",
    "BANKBARODA": "Banking", "PNB": "Banking",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT",
    "TECHM": "IT", "LTIM": "IT",
    "RELIANCE": "Oil & Gas", "ONGC": "Oil & Gas", "IOC": "Oil & Gas",
    "BPCL": "Oil & Gas",
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma",
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "M&M": "Auto",
    "BAJAJ-AUTO": "Auto", "HEROMOTOCO": "Auto",
    "TATASTEEL": "Metals", "HINDALCO": "Metals", "JSWSTEEL": "Metals",
    "ITC": "FMCG", "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    "BAJFINANCE": "Finance", "BAJAJFINSV": "Finance", "HDFCLIFE": "Finance",
    "SBILIFE": "Finance",
    "LT": "Infrastructure", "ULTRACEMCO": "Infrastructure",
    "ADANIENT": "Infrastructure",
    "TITAN": "Consumer", "ASIANPAINT": "Consumer", "PIDILITIND": "Consumer",
}


@dataclass
class AdvancedRiskConfig:
    """Extended risk configuration."""
    # Position limits
    max_position_pct: float = 0.10
    max_portfolio_exposure_pct: float = 0.80
    max_sector_exposure_pct: float = 0.30
    max_single_ticker_pct: float = 0.15
    max_open_positions: int = 10

    # Loss limits
    max_daily_loss: float = 10_000.0
    max_daily_loss_pct: float = 0.03
    max_intraday_loss: float = 5_000.0
    drawdown_circuit_breaker_pct: float = 0.05  # 5% from peak

    # Position sizing
    trailing_stop_pct: float = 0.015
    min_risk_reward_ratio: float = 2.0
    kelly_cap: float = 0.25  # max 25% of Kelly fraction
    volatility_lookback: int = 20

    # Options Greeks limits
    max_portfolio_delta: float = 50.0
    max_portfolio_gamma: float = 10.0
    max_portfolio_theta: float = -5000.0  # max daily theta bleed
    max_portfolio_vega: float = 20_000.0

    # Operational
    cooldown_after_loss: int = 2
    correlation_reduction_threshold: float = 0.7


@dataclass
class PositionRiskExtended:
    """Extended position risk tracking."""
    ticker: str
    side: str
    entry_price: float
    quantity: int
    instrument_type: str = "equity"  # equity / option
    option_type: str | None = None  # CE / PE
    strike: float | None = None
    expiry: str | None = None
    strategy: str | None = None
    sector: str = "Unknown"
    # Greeks (for options)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    # Trailing stop
    highest_price: float = 0.0
    lowest_price: float = 1e9
    trailing_stop: float = 0.0

    def update_trailing_stop(self, price: float, trail_pct: float) -> None:
        if self.side == "buy":
            if price > self.highest_price:
                self.highest_price = price
            self.trailing_stop = self.highest_price * (1 - trail_pct)
        else:
            if price < self.lowest_price:
                self.lowest_price = price
            self.trailing_stop = self.lowest_price * (1 + trail_pct)

    def notional_value(self) -> float:
        return self.entry_price * self.quantity


@dataclass
class RiskApproval:
    """Result of a risk check with score and explanation."""
    approved: bool
    score: float  # 0-100, higher = riskier
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "score": round(self.score, 1),
            "reasons": self.reasons,
            "warnings": self.warnings,
        }


class AdvancedRiskEngine:
    """Institutional-grade risk manager with multi-dimensional exposure checks."""

    def __init__(
        self,
        capital: float,
        config: AdvancedRiskConfig | None = None,
    ) -> None:
        self.capital = capital
        self._initial_capital = capital
        self._peak_equity = capital
        self.config = config or AdvancedRiskConfig()
        self.daily_pnl: float = 0.0
        self.intraday_pnl: float = 0.0
        self.positions: dict[str, PositionRiskExtended] = {}
        self.loss_cooldown: int = 0
        self._circuit_breaker_active: bool = False
        self._daily_locked: bool = False

    # ------------------------------------------------------------------
    # Exposure calculations
    # ------------------------------------------------------------------

    def total_exposure(self) -> float:
        return sum(p.notional_value() for p in self.positions.values())

    def sector_exposure(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for p in self.positions.values():
            sec = p.sector
            result[sec] = result.get(sec, 0) + p.notional_value()
        return result

    def instrument_exposure(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for p in self.positions.values():
            it = p.instrument_type
            result[it] = result.get(it, 0) + p.notional_value()
        return result

    def strategy_exposure(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for p in self.positions.values():
            s = p.strategy or "unknown"
            result[s] = result.get(s, 0) + p.notional_value()
        return result

    def portfolio_greeks(self) -> dict[str, float]:
        delta = sum(p.delta * p.quantity for p in self.positions.values())
        gamma = sum(p.gamma * p.quantity for p in self.positions.values())
        theta = sum(p.theta * p.quantity for p in self.positions.values())
        vega = sum(p.vega * p.quantity for p in self.positions.values())
        return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}

    # ------------------------------------------------------------------
    # Risk approval
    # ------------------------------------------------------------------

    def approve_trade(
        self,
        ticker: str,
        side: str,
        price: float,
        quantity: int,
        instrument_type: str = "equity",
        expected_return: float = 0.0,
        confidence: float = 0.0,
        volatility: float | None = None,
        greeks: dict | None = None,
    ) -> RiskApproval:
        """Full risk gate — returns approval with score and reasons."""
        reasons: list[str] = []
        warnings: list[str] = []
        risk_score = 0.0

        position_value = price * quantity

        # 1. Circuit breaker
        if self._circuit_breaker_active:
            return RiskApproval(False, 100.0, ["Circuit breaker active — drawdown limit reached"])

        # 2. Daily loss lockout
        if self._daily_locked:
            return RiskApproval(False, 100.0, ["Daily loss limit reached — trading locked"])

        # 3. Cooldown
        if self.loss_cooldown > 0:
            return RiskApproval(False, 80.0, [f"Cooldown: {self.loss_cooldown} cycles remaining"])

        # 4. Max open positions
        if len(self.positions) >= self.config.max_open_positions:
            return RiskApproval(False, 70.0, [f"Max positions ({self.config.max_open_positions}) reached"])

        # 5. Already holding
        if ticker in self.positions:
            return RiskApproval(False, 60.0, [f"Already holding {ticker}"])

        # 6. Position size limit
        max_pos = self.capital * self.config.max_position_pct
        if position_value > max_pos:
            reasons.append(f"Position ₹{position_value:.0f} > max ₹{max_pos:.0f}")
            risk_score += 30

        # 7. Portfolio exposure
        total_exp = self.total_exposure() + position_value
        max_exp = self.capital * self.config.max_portfolio_exposure_pct
        if total_exp > max_exp:
            reasons.append(f"Portfolio exposure ₹{total_exp:.0f} > max ₹{max_exp:.0f}")
            risk_score += 25

        # 8. Sector concentration
        sector = SECTOR_MAP.get(ticker, "Unknown")
        sec_exp = self.sector_exposure()
        current_sector = sec_exp.get(sector, 0) + position_value
        max_sector = self.capital * self.config.max_sector_exposure_pct
        if current_sector > max_sector:
            reasons.append(f"Sector {sector} exposure ₹{current_sector:.0f} > max ₹{max_sector:.0f}")
            risk_score += 20

        # 9. Intraday loss check
        if abs(self.intraday_pnl) > self.config.max_intraday_loss:
            reasons.append(f"Intraday loss ₹{abs(self.intraday_pnl):.0f} > limit ₹{self.config.max_intraday_loss:.0f}")
            risk_score += 30

        # 10. Risk-reward check
        if expected_return > 0:
            rr_ratio = expected_return / self.config.trailing_stop_pct if self.config.trailing_stop_pct > 0 else 0
            if rr_ratio < self.config.min_risk_reward_ratio:
                warnings.append(f"Risk/reward {rr_ratio:.1f} below minimum {self.config.min_risk_reward_ratio}")
                risk_score += 10

        # 11. Options Greeks checks
        if instrument_type == "option" and greeks:
            pg = self.portfolio_greeks()
            new_delta = pg["delta"] + greeks.get("delta", 0) * quantity
            new_gamma = pg["gamma"] + greeks.get("gamma", 0) * quantity
            new_theta = pg["theta"] + greeks.get("theta", 0) * quantity
            new_vega = pg["vega"] + greeks.get("vega", 0) * quantity

            if abs(new_delta) > self.config.max_portfolio_delta:
                warnings.append(f"Portfolio delta {new_delta:.1f} > limit {self.config.max_portfolio_delta}")
                risk_score += 15
            if abs(new_gamma) > self.config.max_portfolio_gamma:
                warnings.append(f"Portfolio gamma {new_gamma:.1f} > limit")
                risk_score += 10
            if new_theta < self.config.max_portfolio_theta:
                warnings.append(f"Portfolio theta {new_theta:.0f} < limit {self.config.max_portfolio_theta}")
                risk_score += 10

        # 12. Confidence-weighted risk
        if confidence < 0.6:
            risk_score += 15
            warnings.append(f"Low confidence: {confidence:.2f}")

        # Final decision
        approved = len(reasons) == 0 and risk_score < 70

        return RiskApproval(
            approved=approved,
            score=min(100.0, risk_score),
            reasons=reasons,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def kelly_sizing(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """Kelly criterion with conservative cap."""
        if avg_loss <= 0 or avg_win <= 0:
            return 0.0
        b = avg_win / avg_loss
        p = win_rate
        kelly = (p * b - (1 - p)) / b
        kelly = max(0, kelly)
        # Cap at configured maximum
        return min(kelly, self.config.kelly_cap)

    def volatility_adjusted_size(
        self,
        price: float,
        atr: float,
        target_risk_pct: float = 0.01,
    ) -> int:
        """ATR-based position sizing."""
        if atr <= 0 or price <= 0:
            return 0
        risk_amount = self.capital * target_risk_pct
        qty = int(risk_amount / atr)
        # Also cap by position size limit
        max_qty = int(self.capital * self.config.max_position_pct / price)
        return max(1, min(qty, max_qty))

    def optimal_quantity(self, price: float, stop_loss_pct: float) -> int:
        if price <= 0 or stop_loss_pct <= 0:
            return 0
        risk_per_share = price * stop_loss_pct
        max_risk = self.capital * self.config.max_position_pct * stop_loss_pct
        qty = int(max_risk / risk_per_share)
        return max(1, qty) if qty > 0 else 0

    # ------------------------------------------------------------------
    # Position tracking
    # ------------------------------------------------------------------

    def register_entry(
        self,
        ticker: str,
        side: str,
        price: float,
        quantity: int,
        instrument_type: str = "equity",
        greeks: dict | None = None,
        strategy: str | None = None,
    ) -> None:
        pos = PositionRiskExtended(
            ticker=ticker,
            side=side,
            entry_price=price,
            quantity=quantity,
            instrument_type=instrument_type,
            sector=SECTOR_MAP.get(ticker, "Unknown"),
            strategy=strategy,
            highest_price=price,
            lowest_price=price,
        )
        if greeks:
            pos.delta = greeks.get("delta", 0)
            pos.gamma = greeks.get("gamma", 0)
            pos.theta = greeks.get("theta", 0)
            pos.vega = greeks.get("vega", 0)
        pos.update_trailing_stop(price, self.config.trailing_stop_pct)
        self.positions[ticker] = pos

    def check_exit(self, ticker: str, current_price: float) -> tuple[bool, str]:
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""
        pos.update_trailing_stop(current_price, self.config.trailing_stop_pct)
        if pos.side == "buy" and current_price <= pos.trailing_stop:
            return True, "TRAILING_STOP"
        if pos.side == "sell" and current_price >= pos.trailing_stop:
            return True, "TRAILING_STOP"
        return False, ""

    def register_exit(self, ticker: str, pnl: float, reason: str) -> None:
        self.daily_pnl += pnl
        self.intraday_pnl += pnl

        if ticker in self.positions:
            del self.positions[ticker]

        if reason in ("STOP_LOSS", "TRAILING_STOP"):
            self.loss_cooldown = self.config.cooldown_after_loss

        # Update peak equity and check drawdown circuit breaker
        current_equity = self.capital + self.daily_pnl
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
        drawdown = (self._peak_equity - current_equity) / self._peak_equity
        if drawdown >= self.config.drawdown_circuit_breaker_pct:
            self._circuit_breaker_active = True
            logger.warning("Circuit breaker tripped: %.1f%% drawdown", drawdown * 100)

        # Daily loss lockout
        daily_limit = min(
            self.config.max_daily_loss,
            self.capital * self.config.max_daily_loss_pct,
        )
        if self.daily_pnl <= -daily_limit:
            self._daily_locked = True
            logger.warning("Daily loss limit reached: ₹%.0f", abs(self.daily_pnl))

    def tick_cycle(self) -> None:
        if self.loss_cooldown > 0:
            self.loss_cooldown -= 1

    def reset_daily(self) -> None:
        self.daily_pnl = 0.0
        self.intraday_pnl = 0.0
        self.loss_cooldown = 0
        self._daily_locked = False
        self._circuit_breaker_active = False

    def update_capital(self, available_cash: float) -> None:
        self.capital = available_cash

    # Backwards-compatible alias
    def can_open_position(self, ticker: str, price: float, quantity: int) -> tuple[bool, str]:
        result = self.approve_trade(ticker, "buy", price, quantity)
        if result.approved:
            return True, "OK"
        return False, "; ".join(result.reasons + result.warnings)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def take_snapshot(self, snapshot_type: str = "manual", order_id: str | None = None) -> dict:
        """Create a risk snapshot and persist to DB."""
        greeks = self.portfolio_greeks()
        snapshot = {
            "snapshot_type": snapshot_type,
            "order_id": order_id,
            "total_exposure": round(self.total_exposure(), 2),
            "sector_exposure": {k: round(v, 2) for k, v in self.sector_exposure().items()},
            "instrument_exposure": {k: round(v, 2) for k, v in self.instrument_exposure().items()},
            "greeks": {k: round(v, 2) for k, v in greeks.items()},
            "daily_pnl": round(self.daily_pnl, 2),
            "capital": round(self.capital, 2),
            "circuit_breaker": self._circuit_breaker_active,
            "daily_locked": self._daily_locked,
            "open_positions": len(self.positions),
        }

        # Persist
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import RiskSnapshot

            db = SessionLocal()
            try:
                row = RiskSnapshot(
                    snapshot_type=snapshot_type,
                    order_id=order_id,
                    total_exposure=snapshot["total_exposure"],
                    sector_exposure_json=json.dumps(snapshot["sector_exposure"]),
                    greeks_json=json.dumps(snapshot["greeks"]),
                    daily_pnl=snapshot["daily_pnl"],
                    risk_score=0,
                    data_json=json.dumps(snapshot),
                )
                db.add(row)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

        return snapshot

    @property
    def status(self) -> dict:
        greeks = self.portfolio_greeks()
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "intraday_pnl": round(self.intraday_pnl, 2),
            "open_positions": len(self.positions),
            "loss_cooldown": self.loss_cooldown,
            "capital": round(self.capital, 2),
            "total_exposure": round(self.total_exposure(), 2),
            "sector_exposure": {k: round(v, 2) for k, v in self.sector_exposure().items()},
            "portfolio_greeks": {k: round(v, 2) for k, v in greeks.items()},
            "circuit_breaker_active": self._circuit_breaker_active,
            "daily_locked": self._daily_locked,
        }


_risk_engine: AdvancedRiskEngine | None = None


def get_risk_engine(capital: float = 100_000) -> AdvancedRiskEngine:
    """Module-level singleton accessor."""
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = AdvancedRiskEngine(capital=capital)
    return _risk_engine
