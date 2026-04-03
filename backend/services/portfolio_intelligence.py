"""Portfolio intelligence — advanced analytics for paper and live portfolios.

Provides: realized/unrealized P&L decomposition, exposure heatmaps,
per-strategy/symbol attribution, Greeks summary, daily performance reports,
and capital allocation recommendations.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PortfolioMetrics:
    """Comprehensive portfolio performance metrics."""
    total_equity: float = 0.0
    cash: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_pnl: float = 0.0
    total_charges: float = 0.0
    net_pnl: float = 0.0
    # Risk-adjusted
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    # Exposure
    total_exposure: float = 0.0
    exposure_pct: float = 0.0
    # Attribution
    by_strategy: dict[str, float] = field(default_factory=dict)
    by_symbol: dict[str, float] = field(default_factory=dict)
    by_sector: dict[str, float] = field(default_factory=dict)
    # Greeks
    portfolio_delta: float = 0.0
    portfolio_gamma: float = 0.0
    portfolio_theta: float = 0.0
    portfolio_vega: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_equity": round(self.total_equity, 2),
            "cash": round(self.cash, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_charges": round(self.total_charges, 2),
            "net_pnl": round(self.net_pnl, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3) if self.sharpe_ratio else None,
            "sortino_ratio": round(self.sortino_ratio, 3) if self.sortino_ratio else None,
            "calmar_ratio": round(self.calmar_ratio, 3) if self.calmar_ratio else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "win_rate": round(self.win_rate, 3),
            "profit_factor": round(self.profit_factor, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "total_exposure": round(self.total_exposure, 2),
            "exposure_pct": round(self.exposure_pct, 3),
            "by_strategy": {k: round(v, 2) for k, v in self.by_strategy.items()},
            "by_symbol": {k: round(v, 2) for k, v in self.by_symbol.items()},
            "by_sector": {k: round(v, 2) for k, v in self.by_sector.items()},
            "portfolio_delta": round(self.portfolio_delta, 2),
            "portfolio_gamma": round(self.portfolio_gamma, 3),
            "portfolio_theta": round(self.portfolio_theta, 2),
            "portfolio_vega": round(self.portfolio_vega, 2),
        }


class PortfolioIntelligence:
    """Advanced portfolio analytics engine."""

    def __init__(self) -> None:
        pass

    def compute_metrics(
        self,
        equity_curve: list[dict],
        trades: list[dict],
        positions: dict[str, dict],
        cash: float,
        initial_capital: float = 100_000.0,
    ) -> PortfolioMetrics:
        """Compute comprehensive portfolio metrics.

        Args:
            equity_curve: list of {"date": ..., "equity": ...}
            trades: list of trade dicts from journal or bot
            positions: current open positions
            cash: current cash balance
            initial_capital: starting capital
        """
        m = PortfolioMetrics()
        m.cash = cash

        # P&L decomposition
        unrealized = 0.0
        total_exposure = 0.0
        for ticker, pos in positions.items():
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            qty = pos.get("quantity", 0)
            side = pos.get("side", "buy")

            notional = current * qty
            total_exposure += notional

            if side == "buy":
                unrealized += (current - entry) * qty
            else:
                unrealized += (entry - current) * qty

        m.unrealized_pnl = unrealized
        m.total_exposure = total_exposure
        m.total_equity = cash + unrealized + total_exposure

        # Equity curve based metrics
        equities = [e.get("equity", initial_capital) for e in equity_curve] if equity_curve else [initial_capital]
        if len(equities) >= 2:
            returns = np.diff(equities) / np.array(equities[:-1])
            returns = returns[np.isfinite(returns)]

            if len(returns) > 1:
                avg_r = float(np.mean(returns))
                std_r = float(np.std(returns))

                m.sharpe_ratio = (avg_r / std_r * np.sqrt(252)) if std_r > 0 else 0

                downside = returns[returns < 0]
                down_std = float(np.std(downside)) if len(downside) > 0 else 1e-9
                m.sortino_ratio = (avg_r / down_std * np.sqrt(252)) if down_std > 0 else 0

            # Max drawdown
            peak = equities[0]
            max_dd = 0.0
            for e in equities:
                if e > peak:
                    peak = e
                dd = (peak - e) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            m.max_drawdown_pct = max_dd

            # Calmar
            total_return = (equities[-1] - equities[0]) / equities[0] if equities[0] > 0 else 0
            m.calmar_ratio = (total_return / max_dd) if max_dd > 0 else 0

        m.exposure_pct = total_exposure / m.total_equity if m.total_equity > 0 else 0

        # Trade analysis
        closed_trades = [t for t in trades if t.get("exit_price") or t.get("action") in ("STOP_LOSS", "TAKE_PROFIT", "EXIT")]
        m.total_trades = len(closed_trades)

        wins = []
        losses = []
        realized = 0.0
        charges = 0.0
        by_strategy: dict[str, float] = {}
        by_symbol: dict[str, float] = {}
        by_sector: dict[str, float] = {}

        for t in closed_trades:
            pnl = t.get("net_pnl", t.get("gross_pnl", 0))
            realized += pnl
            charges += t.get("charges", 0)

            if pnl > 0:
                wins.append(pnl)
            elif pnl < 0:
                losses.append(pnl)

            strat = t.get("strategy_used", t.get("strategy", "unknown"))
            by_strategy[strat] = by_strategy.get(strat, 0) + pnl

            sym = t.get("ticker", "unknown")
            by_symbol[sym] = by_symbol.get(sym, 0) + pnl

            sector = self._get_sector(sym)
            by_sector[sector] = by_sector.get(sector, 0) + pnl

        m.realized_pnl = realized
        m.total_pnl = realized + unrealized
        m.total_charges = charges
        m.net_pnl = realized + unrealized - charges
        m.winning_trades = len(wins)
        m.losing_trades = len(losses)
        m.win_rate = len(wins) / m.total_trades if m.total_trades > 0 else 0
        m.avg_win = sum(wins) / len(wins) if wins else 0
        m.avg_loss = sum(losses) / len(losses) if losses else 0
        m.profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf") if wins else 0
        m.by_strategy = by_strategy
        m.by_symbol = by_symbol
        m.by_sector = by_sector

        # Greeks from positions
        for pos in positions.values():
            m.portfolio_delta += pos.get("delta", 0) * pos.get("quantity", 0)
            m.portfolio_gamma += pos.get("gamma", 0) * pos.get("quantity", 0)
            m.portfolio_theta += pos.get("theta", 0) * pos.get("quantity", 0)
            m.portfolio_vega += pos.get("vega", 0) * pos.get("quantity", 0)

        return m

    def exposure_heatmap(
        self, positions: dict[str, dict]
    ) -> dict[str, dict[str, float]]:
        """Generate exposure heatmap by sector x instrument type."""
        heatmap: dict[str, dict[str, float]] = {}
        for ticker, pos in positions.items():
            sector = self._get_sector(ticker)
            inst_type = pos.get("instrument_type", "equity")
            notional = pos.get("current_price", pos.get("entry_price", 0)) * pos.get("quantity", 0)
            if sector not in heatmap:
                heatmap[sector] = {}
            heatmap[sector][inst_type] = heatmap[sector].get(inst_type, 0) + notional
        return heatmap

    def capital_allocation_recommendation(
        self,
        total_capital: float,
        current_positions: dict[str, dict],
        regime: str = "unknown",
    ) -> dict:
        """Recommend capital allocation based on regime and current state."""
        n_positions = len(current_positions)
        current_exposure = sum(
            pos.get("current_price", 0) * pos.get("quantity", 0)
            for pos in current_positions.values()
        )
        free_capital = total_capital - current_exposure

        # Regime-based allocation
        if regime in ("crash", "high_vol"):
            max_allocation = 0.3
            recommendation = "Reduce exposure. High volatility detected."
        elif regime in ("trending_up",):
            max_allocation = 0.7
            recommendation = "Favorable conditions. Can increase allocation."
        elif regime in ("range_bound", "low_vol"):
            max_allocation = 0.5
            recommendation = "Moderate allocation. Consider options strategies."
        else:
            max_allocation = 0.5
            recommendation = "Standard allocation."

        target_exposure = total_capital * max_allocation
        adjustment = target_exposure - current_exposure

        return {
            "total_capital": round(total_capital, 2),
            "current_exposure": round(current_exposure, 2),
            "free_capital": round(free_capital, 2),
            "exposure_pct": round(current_exposure / total_capital, 3) if total_capital > 0 else 0,
            "target_exposure_pct": max_allocation,
            "target_exposure": round(target_exposure, 2),
            "adjustment_needed": round(adjustment, 2),
            "action": "increase" if adjustment > 0 else "reduce" if adjustment < 0 else "hold",
            "recommendation": recommendation,
            "regime": regime,
        }

    def daily_summary(
        self,
        equity_curve: list[dict],
        trades_today: list[dict],
        positions: dict[str, dict],
    ) -> dict:
        """Generate a daily performance summary."""
        today_pnl = sum(t.get("net_pnl", t.get("gross_pnl", 0)) for t in trades_today)
        today_trades = len(trades_today)
        wins = sum(1 for t in trades_today if t.get("net_pnl", t.get("gross_pnl", 0)) > 0)

        eq = equity_curve[-1].get("equity", 0) if equity_curve else 0
        prev_eq = equity_curve[-2].get("equity", eq) if len(equity_curve) >= 2 else eq
        daily_return = (eq - prev_eq) / prev_eq if prev_eq > 0 else 0

        return {
            "date": date.today().isoformat(),
            "equity": round(eq, 2),
            "daily_pnl": round(today_pnl, 2),
            "daily_return_pct": round(daily_return * 100, 3),
            "trades_today": today_trades,
            "wins": wins,
            "losses": today_trades - wins,
            "win_rate": round(wins / today_trades, 3) if today_trades > 0 else 0,
            "active_positions": len(positions),
        }

    def _get_sector(self, ticker: str) -> str:
        try:
            from backend.services.advanced_risk import SECTOR_MAP
            return SECTOR_MAP.get(ticker, "Other")
        except Exception:
            return "Other"


_portfolio_intelligence: PortfolioIntelligence | None = None


def get_portfolio_intelligence() -> PortfolioIntelligence:
    """Module-level singleton accessor."""
    global _portfolio_intelligence
    if _portfolio_intelligence is None:
        _portfolio_intelligence = PortfolioIntelligence()
    return _portfolio_intelligence
