"""Unified trading runner for paper / live / backtest parity.

Provides a single ``TradingRunner`` class that orchestrates the signal →
strategy → execution pipeline identically across modes.  The only
difference is which ``ExecutionAdapter`` and data source are injected.

Usage
-----
    # Paper trading
    runner = TradingRunner(mode=ExecutionMode.PAPER)
    runner.on_market_data(prices, features, timestamp)

    # Backtesting (bar replay)
    runner = TradingRunner(mode=ExecutionMode.BACKTEST)
    for bar in historical_bars:
        runner.on_market_data(bar.prices, bar.features, bar.timestamp)
    results = runner.get_results()

    # Live trading
    runner = TradingRunner(mode=ExecutionMode.LIVE)
    runner.on_market_data(prices, features, timestamp)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from backend.shared.schemas import (
    ExecutionMode,
    OrderStatus,
    PortfolioState,
    RiskLimits,
    SignalDirection,
    TradeResult,
    TradingSignal,
)
from backend.shared.strategy_engine import StrategyEngine
from backend.shared.execution import (
    BacktestExecutor,
    ExecutionAdapter,
    LiveExecutor,
    PaperExecutor,
    SimulationConfig,
    apply_fill_to_portfolio,
)
if TYPE_CHECKING:
    from backend.shared.signal_generator import SignalGenerator

logger = logging.getLogger(__name__)


class TradingRunner:
    """Unified trading runner that ensures paper / backtest / live parity.

    All three modes flow through:.
        signals → strategy_engine.check_exits() → strategy_engine.on_signal()
                → executor.submit_order() → apply_fill_to_portfolio()
    """

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.PAPER,
        initial_capital: float = 100_000.0,
        risk_limits: RiskLimits | None = None,
        sim_config: SimulationConfig | None = None,
        signal_generator: "SignalGenerator | None" = None,
    ) -> None:
        self.mode = mode
        self.risk_limits = risk_limits or RiskLimits()
        self.strategy = StrategyEngine(self.risk_limits)
        self.signal_gen = signal_generator

        # Select executor based on mode
        if mode == ExecutionMode.BACKTEST:
            self.executor: ExecutionAdapter = BacktestExecutor(
                sim_config or SimulationConfig()
            )
        elif mode == ExecutionMode.PAPER:
            self.executor = PaperExecutor(
                sim_config or SimulationConfig()
            )
        else:
            self.executor = LiveExecutor()

        self.portfolio = PortfolioState(
            cash=initial_capital,
            execution_mode=mode,
        )

        self._bar_index = 0
        self._completed_trades: list[TradeResult] = []
        self._rejected_count = 0
        self._no_trade_count = 0

    # ------------------------------------------------------------------
    #  Main entry point — called on every bar / tick
    # ------------------------------------------------------------------

    def on_market_data(
        self,
        prices: dict[str, float],
        signals: list[TradingSignal] | None = None,
        features: list[dict[str, Any]] | None = None,
        timestamp: datetime | None = None,
    ) -> list[TradeResult]:
        """Process one bar of market data.

        Either pass pre-computed ``signals`` or raw ``features`` (which
        will be fed through the signal generator).

        Returns a list of completed trades from this bar.
        """
        ts = timestamp or datetime.now(timezone.utc)
        self.strategy.bar_index = self._bar_index
        bar_trades: list[TradeResult] = []

        # Reset daily counters (caller should reset at day boundaries)
        # For intra-day this is a no-op.

        # --- Generate signals if not provided ---
        if signals is None and features is not None and self.signal_gen is not None:
            signals = self.signal_gen.generate_signals(features, prices, ts)

        if signals is None:
            signals = []

        # --- 1. Check exits on open positions ---
        exit_orders = self.strategy.check_exits(self.portfolio, prices)
        for order in exit_orders:
            price = prices.get(order.instrument)
            if price is None:
                continue
            state = self.executor.submit_order(order, self.portfolio, price, ts)
            if state.status in {OrderStatus.FILLED, OrderStatus.PARTIAL}:
                for fill in state.fills:
                    result = apply_fill_to_portfolio(
                        fill, self.portfolio, order,
                        self.executor, self._bar_index,
                    )
                    if result:
                        self._completed_trades.append(result)
                        bar_trades.append(result)

        # --- 2. Process new signals ---
        actionable = [s for s in signals if not s.no_trade_flag]
        self._no_trade_count += len(signals) - len(actionable)

        batched_orders = self.strategy.build_orders(actionable, self.portfolio, prices)
        for signal in actionable:
            # keep rejection accounting comparable with previous behavior
            if signal.signal_direction != SignalDirection.FLAT:
                has_signal_order = any(
                    o.signal is signal or o.instrument == signal.instrument
                    for o in batched_orders
                )
                if not has_signal_order:
                    self._rejected_count += 1

        for order in batched_orders:
            price = prices.get(order.instrument)
            if price is None:
                continue

            state = self.executor.submit_order(
                order, self.portfolio, price, ts,
            )
            if state.status in {OrderStatus.FILLED, OrderStatus.PARTIAL}:
                for fill in state.fills:
                    result = apply_fill_to_portfolio(
                        fill, self.portfolio, order,
                        self.executor, self._bar_index,
                    )
                    if result:
                        self._completed_trades.append(result)
                        bar_trades.append(result)
            elif state.status == OrderStatus.REJECTED:
                self._rejected_count += 1

        # --- 3. Mark to market ---
        for instrument, pos in self.portfolio.positions.items():
            if pos.is_open and instrument in prices:
                pos.mark_to_market(prices[instrument])

        self.strategy.advance_bar(self.portfolio)
        self._bar_index = self.strategy.bar_index
        return bar_trades

    # ------------------------------------------------------------------
    #  Reset daily counters (call at start of each trading day)
    # ------------------------------------------------------------------

    def reset_daily(self) -> None:
        self.portfolio.daily_pnl = 0.0
        self.portfolio.daily_trades = 0
        self.portfolio.daily_losses = 0

    # ------------------------------------------------------------------
    #  Results
    # ------------------------------------------------------------------

    @property
    def completed_trades(self) -> list[TradeResult]:
        return self._completed_trades

    @property
    def equity(self) -> float:
        return self.portfolio.equity

    @property
    def stats(self) -> dict[str, Any]:
        pnls = [t.pnl for t in self._completed_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        return {
            "mode": self.mode.value,
            "equity": round(self.portfolio.equity, 2),
            "cash": round(self.portfolio.cash, 2),
            "open_positions": self.portfolio.open_position_count,
            "total_trades": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(pnls) * 100, 2) if pnls else 0,
            "total_pnl": round(sum(pnls), 2) if pnls else 0,
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "total_charges": round(self.portfolio.total_commission, 2),
            "rejected": self._rejected_count,
            "no_trade": self._no_trade_count,
        }
