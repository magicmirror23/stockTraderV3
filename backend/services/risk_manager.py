"""Portfolio risk manager used by trading-service runtime.

This class mirrors the shared risk logic used by backtest/paper/live:
- conservative position and portfolio caps
- sector and heat exposure checks
- symbol cooldown after stop-outs
- trailing/time-based stop supervision
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Configurable portfolio constraints for runtime trading."""

    max_position_pct: float = 0.10
    max_capital_per_trade_pct: float = 0.10
    max_portfolio_risk_pct: float = 0.30
    max_portfolio_heat_pct: float = 0.12
    max_sector_exposure_pct: float = 0.35
    max_daily_loss: float = 5_000.0
    max_daily_loss_pct: float = 0.02
    trailing_stop_pct: float = 0.015
    min_risk_reward_ratio: float = 2.0
    max_open_positions: int = 5
    cooldown_after_loss: int = 2
    symbol_cooldown_cycles: int = 3
    default_stop_loss_pct: float = 0.02
    time_stop_cycles: int = 120
    profit_lock_fraction: float = 0.35


@dataclass
class PositionRisk:
    """Live risk state for a single position."""

    ticker: str
    side: str
    entry_price: float
    quantity: int
    sector: str = "UNKNOWN"
    risk_per_share: float = 0.0
    entry_cycle: int = 0
    highest_price: float = 0.0
    lowest_price: float = 1e9
    trailing_stop: float = 0.0
    max_favorable_excursion: float = 0.0

    def update_trailing_stop(self, current_price: float, trail_pct: float) -> None:
        if self.side == "buy":
            if current_price > self.highest_price:
                self.highest_price = current_price
            self.trailing_stop = self.highest_price * (1 - trail_pct)
            self.max_favorable_excursion = max(
                self.max_favorable_excursion,
                current_price - self.entry_price,
            )
        else:
            if current_price < self.lowest_price:
                self.lowest_price = current_price
            self.trailing_stop = self.lowest_price * (1 + trail_pct)
            self.max_favorable_excursion = max(
                self.max_favorable_excursion,
                self.entry_price - current_price,
            )

    def should_exit_trailing(self, current_price: float) -> bool:
        if self.trailing_stop <= 0:
            return False
        if self.side == "buy":
            return current_price <= self.trailing_stop
        return current_price >= self.trailing_stop


class RiskManager:
    """Portfolio-level risk manager."""

    def __init__(self, capital: float, config: RiskConfig | None = None) -> None:
        self.capital = capital
        self._initial_capital = max(capital, 1.0)
        self.config = config or RiskConfig()
        self.daily_pnl: float = 0.0
        self.positions: dict[str, PositionRisk] = {}
        self.loss_cooldown: int = 0
        self._cycle_index: int = 0
        self._symbol_cooldowns: dict[str, int] = {}

    def update_capital(self, available_cash: float) -> None:
        self.capital = max(available_cash, 0.0)
        logger.debug("RiskManager capital updated to %.2f", available_cash)

    def _sector_exposure(self) -> dict[str, float]:
        exposure: dict[str, float] = {}
        for p in self.positions.values():
            value = p.entry_price * p.quantity
            exposure[p.sector] = exposure.get(p.sector, 0.0) + value
        return exposure

    def _portfolio_heat_value(self) -> float:
        return sum(max(p.risk_per_share, 0.0) * p.quantity for p in self.positions.values())

    def can_open_position(
        self,
        ticker: str,
        price: float,
        quantity: int,
        sector: str = "UNKNOWN",
        stop_loss_pct: float | None = None,
    ) -> tuple[bool, str]:
        """Check whether a new position is allowed under risk rules."""
        if quantity <= 0 or price <= 0:
            return False, "Invalid order size"

        if self.loss_cooldown > 0:
            return False, f"Cooldown active ({self.loss_cooldown} cycles remaining after stop-loss)"

        if self._symbol_cooldowns.get(ticker, 0) > 0:
            return False, f"Symbol cooldown active for {ticker}"

        daily_limit = min(self.config.max_daily_loss, self.capital * self.config.max_daily_loss_pct)
        if self.daily_pnl <= -daily_limit:
            return False, f"Daily loss limit reached ({daily_limit:.0f})"

        if len(self.positions) >= self.config.max_open_positions:
            return False, f"Max open positions ({self.config.max_open_positions}) reached"

        if ticker in self.positions:
            return False, f"Already holding {ticker}"

        position_value = price * quantity
        max_position = self.capital * min(
            self.config.max_position_pct,
            self.config.max_capital_per_trade_pct,
        )
        if position_value > max_position:
            return False, f"Position {position_value:.0f} exceeds max {max_position:.0f}"

        total_exposure = sum(p.entry_price * p.quantity for p in self.positions.values()) + position_value
        max_exposure = self.capital * self.config.max_portfolio_risk_pct
        if total_exposure > max_exposure:
            return False, f"Portfolio exposure {total_exposure:.0f} would exceed max {max_exposure:.0f}"

        sector_exposure = self._sector_exposure().get(sector, 0.0) + position_value
        if sector_exposure > self.capital * self.config.max_sector_exposure_pct:
            return False, f"Sector exposure limit exceeded for {sector}"

        effective_sl = stop_loss_pct or self.config.default_stop_loss_pct
        risk_per_share = max(price * effective_sl, price * 0.005)
        projected_heat = self._portfolio_heat_value() + risk_per_share * quantity
        max_heat_value = self.capital * self.config.max_portfolio_heat_pct
        if projected_heat > max_heat_value:
            return False, "Portfolio heat limit exceeded"

        return True, "OK"

    def optimal_quantity(self, price: float, stop_loss_pct: float) -> int:
        if price <= 0 or stop_loss_pct <= 0:
            return 0

        risk_per_share = price * stop_loss_pct
        max_risk_amount = self.capital * self.config.max_capital_per_trade_pct * stop_loss_pct
        qty = int(max_risk_amount / max(risk_per_share, 1e-9))
        return max(1, qty) if qty > 0 else 0

    def register_entry(
        self,
        ticker: str,
        side: str,
        price: float,
        quantity: int,
        sector: str = "UNKNOWN",
        stop_loss_pct: float | None = None,
    ) -> None:
        effective_sl = stop_loss_pct or self.config.default_stop_loss_pct
        pos = PositionRisk(
            ticker=ticker,
            side=side,
            entry_price=price,
            quantity=quantity,
            sector=sector,
            risk_per_share=max(price * effective_sl, price * 0.005),
            entry_cycle=self._cycle_index,
            highest_price=price,
            lowest_price=price,
        )
        pos.update_trailing_stop(price, self.config.trailing_stop_pct)
        self.positions[ticker] = pos

    def check_exit(self, ticker: str, current_price: float) -> tuple[bool, str]:
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""

        pos.update_trailing_stop(current_price, self.config.trailing_stop_pct)
        if pos.should_exit_trailing(current_price):
            return True, "TRAILING_STOP"

        # Time stop: avoid stale capital lock.
        if (self._cycle_index - pos.entry_cycle) >= self.config.time_stop_cycles:
            return True, "TIME_STOP"

        # Profit protection: lock part of open gains.
        if pos.max_favorable_excursion > 0:
            lock_price = pos.entry_price + pos.max_favorable_excursion * self.config.profit_lock_fraction
            if pos.side == "buy" and current_price <= lock_price and lock_price > pos.entry_price:
                return True, "PROFIT_PROTECT"

        return False, ""

    def register_exit(self, ticker: str, pnl: float, reason: str) -> None:
        self.daily_pnl += pnl
        if ticker in self.positions:
            del self.positions[ticker]

        if reason in ("STOP_LOSS", "TRAILING_STOP", "TIME_STOP"):
            self.loss_cooldown = self.config.cooldown_after_loss
            self._symbol_cooldowns[ticker] = self.config.symbol_cooldown_cycles
            logger.info(
                "Risk cooldown on %s for %d cycles (reason=%s)",
                ticker,
                self.config.symbol_cooldown_cycles,
                reason,
            )

    def tick_cycle(self) -> None:
        self._cycle_index += 1
        if self.loss_cooldown > 0:
            self.loss_cooldown -= 1
        expired = [sym for sym, left in self._symbol_cooldowns.items() if left <= 1]
        for sym in expired:
            self._symbol_cooldowns.pop(sym, None)
        for sym in list(self._symbol_cooldowns):
            if sym not in expired:
                self._symbol_cooldowns[sym] -= 1

    def reset_daily(self) -> None:
        self.daily_pnl = 0.0
        self.loss_cooldown = 0

    def meets_risk_reward(self, expected_return_pct: float, stop_loss_pct: float) -> bool:
        if stop_loss_pct <= 0:
            return False
        ratio = expected_return_pct / stop_loss_pct
        return ratio >= self.config.min_risk_reward_ratio

    @property
    def status(self) -> dict:
        exposure = sum(p.entry_price * p.quantity for p in self.positions.values())
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.positions),
            "loss_cooldown": self.loss_cooldown,
            "capital": self.capital,
            "portfolio_exposure": round(exposure, 2),
            "portfolio_heat": round(self._portfolio_heat_value(), 2),
            "symbol_cooldowns": dict(self._symbol_cooldowns),
            "cycle_index": self._cycle_index,
        }
