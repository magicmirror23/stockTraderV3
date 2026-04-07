from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from backend.shared.execution import BacktestExecutor, SimulationConfig, apply_fill_to_portfolio
from backend.shared.runner import TradingRunner
from backend.shared.schemas import (
    ExecutionMode,
    OrderSide,
    OrderStatus,
    PortfolioState,
    Position,
    RegimeLabel,
    RiskLimits,
    SignalDirection,
    StrategyMode,
    TradingSignal,
)
from backend.shared.strategy_engine import RiskGate, StrategyEngine, select_strategy_mode, size_position


def _sig(
    instrument: str = "RELIANCE",
    direction: SignalDirection = SignalDirection.LONG,
    confidence: float = 0.75,
    volatility: float = 0.2,
    regime: RegimeLabel = RegimeLabel.TRENDING_UP,
    sector: str = "ENERGY",
    mode: StrategyMode = StrategyMode.AUTO,
) -> TradingSignal:
    return TradingSignal(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1),
        timeframe="1d",
        signal_direction=direction,
        direction_probability=confidence,
        expected_move=0.02,
        expected_volatility=volatility,
        confidence_score=confidence,
        regime_label=regime,
        sector=sector,
        strategy_mode_hint=mode,
        metadata={"atr_14": 2.0, "momentum_10": 0.05, "adx_14": 24.0, "rsi_14": 48.0},
    )


def test_regime_strategy_switching():
    assert select_strategy_mode(_sig(regime=RegimeLabel.TRENDING_UP)) == StrategyMode.MOMENTUM
    assert select_strategy_mode(_sig(regime=RegimeLabel.BREAKOUT)) == StrategyMode.BREAKOUT
    assert select_strategy_mode(_sig(regime=RegimeLabel.RANGE_BOUND)) == StrategyMode.MEAN_REVERSION
    assert select_strategy_mode(_sig(regime=RegimeLabel.LOW_VOLATILITY)) == StrategyMode.LOW_VOL_TREND


def test_sector_exposure_cap_blocks_entry():
    limits = RiskLimits(max_sector_exposure_pct=0.25)
    gate = RiskGate(limits)
    portfolio = PortfolioState(cash=100_000)
    portfolio.positions["ICICIBANK"] = Position(
        instrument="ICICIBANK",
        quantity=250,
        avg_entry_price=100.0,
        sector="BANKING",
    )
    signal = _sig(instrument="HDFCBANK", sector="BANKING")
    ok, reason, qty = gate.approve(
        signal,
        portfolio,
        proposed_qty=20,
        proposed_price=100.0,
        proposed_stop_loss=95.0,
        sector="BANKING",
    )
    assert not ok
    assert "sector_exposure_limit" in reason
    assert qty == 0


def test_portfolio_heat_cap_reduces_or_blocks_size():
    limits = RiskLimits(max_portfolio_heat_pct=0.02)
    gate = RiskGate(limits)
    portfolio = PortfolioState(cash=100_000)
    portfolio.positions["TCS"] = Position(
        instrument="TCS",
        quantity=100,
        avg_entry_price=100.0,
        stop_loss=98.0,
        sector="IT",
    )

    signal = _sig(instrument="INFY", sector="IT")
    ok, reason, qty = gate.approve(
        signal,
        portfolio,
        proposed_qty=100,
        proposed_price=100.0,
        proposed_stop_loss=90.0,
        sector="IT",
    )
    assert (not ok and qty == 0) or (ok and qty < 100)
    if not ok:
        assert "portfolio_heat_limit" in reason


def test_symbol_cooldown_set_on_stop_loss_exit():
    engine = StrategyEngine(RiskLimits(symbol_cooldown_bars=3))
    portfolio = PortfolioState(cash=100_000, execution_mode=ExecutionMode.BACKTEST)
    portfolio.positions["RELIANCE"] = Position(
        instrument="RELIANCE",
        quantity=10,
        avg_entry_price=100.0,
        stop_loss=98.0,
        sector="ENERGY",
    )
    executor = BacktestExecutor(SimulationConfig(slippage_pct=0, fill_probability=1.0, commission_flat=0, use_angel_charges=False))
    orders = engine.check_exits(portfolio, {"RELIANCE": 97.0})
    assert len(orders) == 1
    assert orders[0].metadata.get("cooldown_bars") == 3

    state = executor.submit_order(orders[0], portfolio, 97.0, datetime(2026, 1, 1))
    assert state.status in {OrderStatus.FILLED, OrderStatus.PARTIAL}
    for fill in state.fills:
        apply_fill_to_portfolio(fill, portfolio, orders[0], executor, bar_index=1)
    assert portfolio.in_cooldown("RELIANCE")


def test_sizing_confidence_and_volatility_respected():
    limits = RiskLimits()
    portfolio = PortfolioState(cash=100_000)
    low_conf = _sig(confidence=0.56, volatility=0.2)
    high_conf = _sig(confidence=0.85, volatility=0.2)
    high_vol = _sig(confidence=0.85, volatility=0.7)

    qty_low = size_position(low_conf, portfolio, limits, 100.0, StrategyMode.MOMENTUM)
    qty_high = size_position(high_conf, portfolio, limits, 100.0, StrategyMode.MOMENTUM)
    qty_high_vol = size_position(high_vol, portfolio, limits, 100.0, StrategyMode.MOMENTUM)

    assert qty_high >= qty_low
    assert qty_high_vol < qty_high


def test_decision_parity_across_modes():
    limits = RiskLimits()
    engine = StrategyEngine(limits)
    signal = _sig(instrument="AXISBANK", sector="BANKING", confidence=0.8)
    prices = {"AXISBANK": 100.0}

    orders = []
    for mode in (ExecutionMode.BACKTEST, ExecutionMode.PAPER, ExecutionMode.LIVE):
        portfolio = PortfolioState(cash=100_000, execution_mode=mode)
        mode_orders = engine.build_orders([deepcopy(signal)], portfolio, prices)
        assert len(mode_orders) == 1
        orders.append(mode_orders[0])

    assert orders[0].quantity == orders[1].quantity == orders[2].quantity
    assert orders[0].stop_loss == orders[1].stop_loss == orders[2].stop_loss
    assert orders[0].take_profit == orders[1].take_profit == orders[2].take_profit


def test_runner_parity_backtest_vs_paper():
    sim = SimulationConfig(
        slippage_pct=0.0,
        fill_probability=1.0,
        partial_fill_prob=0.0,
        use_angel_charges=False,
        commission_flat=0.0,
    )
    limits = RiskLimits(max_positions=5)
    runner_bt = TradingRunner(mode=ExecutionMode.BACKTEST, initial_capital=100_000, risk_limits=limits, sim_config=sim)
    runner_pp = TradingRunner(mode=ExecutionMode.PAPER, initial_capital=100_000, risk_limits=limits, sim_config=sim)

    day1_prices = {"RELIANCE": 100.0}
    day2_prices = {"RELIANCE": 103.0}
    buy_signal = _sig(instrument="RELIANCE", confidence=0.8)
    flat_signal = _sig(instrument="RELIANCE", direction=SignalDirection.FLAT, confidence=0.8)

    runner_bt.on_market_data(day1_prices, signals=[buy_signal], timestamp=datetime(2026, 1, 1))
    runner_pp.on_market_data(day1_prices, signals=[deepcopy(buy_signal)], timestamp=datetime(2026, 1, 1))
    bt_trades = runner_bt.on_market_data(day2_prices, signals=[flat_signal], timestamp=datetime(2026, 1, 2))
    pp_trades = runner_pp.on_market_data(day2_prices, signals=[deepcopy(flat_signal)], timestamp=datetime(2026, 1, 2))

    assert len(bt_trades) == len(pp_trades) == 1
    assert bt_trades[0].instrument == pp_trades[0].instrument
    assert bt_trades[0].pnl == pp_trades[0].pnl
