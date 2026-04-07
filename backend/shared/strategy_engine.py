"""Shared strategy engine for backtest, paper, and live parity.

This module is the single decision core for:
- signal ingestion and ranking
- regime-aware strategy mode selection
- confidence and risk gating
- volatility-adjusted position sizing
- stop and portfolio risk enforcement

Only execution adapters differ across backtest/paper/live.
"""

from __future__ import annotations

import logging

from backend.shared.schemas import (
    OrderRequest,
    OrderSide,
    OrderType,
    PortfolioState,
    Position,
    RegimeLabel,
    RiskLimits,
    SignalDirection,
    StrategyMode,
    TradingSignal,
)

logger = logging.getLogger(__name__)


# =====================================================================
#  Regime-based strategy mapping and scaling
# =====================================================================


def select_strategy_mode(signal: TradingSignal) -> StrategyMode:
    """Select strategy mode from explicit hint + inferred regime."""
    if signal.strategy_mode_hint != StrategyMode.AUTO:
        return signal.strategy_mode_hint

    if signal.regime_label in (RegimeLabel.TRENDING_UP, RegimeLabel.TRENDING_DOWN):
        return StrategyMode.MOMENTUM
    if signal.regime_label == RegimeLabel.BREAKOUT:
        return StrategyMode.BREAKOUT
    if signal.regime_label == RegimeLabel.RANGE_BOUND:
        return StrategyMode.MEAN_REVERSION
    if signal.regime_label == RegimeLabel.LOW_VOLATILITY:
        return StrategyMode.LOW_VOL_TREND
    if signal.regime_label in (RegimeLabel.HIGH_VOLATILITY, RegimeLabel.CRASH):
        return StrategyMode.LOW_VOL_TREND
    return StrategyMode.MOMENTUM


def _regime_scale(regime: RegimeLabel, limits: RiskLimits) -> float:
    """Return a size multiplier based on the market regime."""
    _map = {
        RegimeLabel.TRENDING_UP: limits.regime_scale_trending,
        RegimeLabel.TRENDING_DOWN: limits.regime_scale_range,
        RegimeLabel.RANGE_BOUND: limits.regime_scale_range,
        RegimeLabel.HIGH_VOLATILITY: limits.regime_scale_high_vol,
        RegimeLabel.LOW_VOLATILITY: 1.0,
        RegimeLabel.BREAKOUT: 1.0,
        RegimeLabel.CRASH: limits.regime_scale_crash,
        RegimeLabel.UNKNOWN: 1.0,
    }
    return _map.get(regime, 1.0)


def _strategy_scale(mode: StrategyMode) -> float:
    _map = {
        StrategyMode.MOMENTUM: 1.0,
        StrategyMode.BREAKOUT: 0.95,
        StrategyMode.MEAN_REVERSION: 0.75,
        StrategyMode.LOW_VOL_TREND: 0.85,
        StrategyMode.AUTO: 1.0,
    }
    return _map.get(mode, 1.0)


def _strategy_rank_bonus(signal: TradingSignal, mode: StrategyMode) -> float:
    """Mode-sensitive ranking adjustment."""
    momentum = float(signal.metadata.get("momentum_10", 0.0)) if signal.metadata else 0.0
    adx = float(signal.metadata.get("adx_14", 0.0)) if signal.metadata else 0.0
    rsi = float(signal.metadata.get("rsi_14", 50.0)) if signal.metadata else 50.0

    if mode == StrategyMode.MOMENTUM:
        return max(momentum, 0.0) + max((adx - 18.0) / 100.0, 0.0)
    if mode == StrategyMode.BREAKOUT:
        return max((adx - 20.0) / 80.0, 0.0)
    if mode == StrategyMode.MEAN_REVERSION:
        return 0.15 if rsi < 35.0 else 0.0
    if mode == StrategyMode.LOW_VOL_TREND:
        vol = max(signal.expected_volatility, 1e-6)
        return min(0.2, 0.08 / vol)
    return 0.0


# =====================================================================
#  Momentum and mode eligibility filters
# =====================================================================


def _momentum_confirms(signal: TradingSignal) -> bool:
    """Check momentum alignment with signal direction."""
    meta = signal.metadata
    if not meta:
        return True

    momentum = meta.get("momentum_10")
    ema_cross = meta.get("ema_crossover")

    if signal.signal_direction == SignalDirection.LONG:
        if momentum is not None and momentum < -0.05:
            return False
        if ema_cross is not None and ema_cross < -0.8:
            return False
    elif signal.signal_direction == SignalDirection.SHORT:
        if momentum is not None and momentum > 0.05:
            return False

    return True


def _mode_allows_signal(signal: TradingSignal, mode: StrategyMode) -> bool:
    """Mode-specific guardrails for conservative deployment."""
    if signal.signal_direction != SignalDirection.LONG:
        return True

    meta = signal.metadata or {}
    momentum = float(meta.get("momentum_10", 0.0))
    adx = float(meta.get("adx_14", 0.0))
    rsi = float(meta.get("rsi_14", 50.0))

    if mode == StrategyMode.MOMENTUM:
        return momentum >= -0.02 and adx >= 14.0
    if mode == StrategyMode.BREAKOUT:
        breakout_score = float(meta.get("breakout_score", 0.0))
        return breakout_score > 0.0 or adx >= 20.0
    if mode == StrategyMode.MEAN_REVERSION:
        return rsi <= 40.0 or momentum <= -0.01
    if mode == StrategyMode.LOW_VOL_TREND:
        return signal.expected_volatility <= 0.35

    return True


# =====================================================================
#  Risk gate
# =====================================================================


class RiskGate:
    """Stateless risk checks applied before every order."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def approve(
        self,
        signal: TradingSignal,
        portfolio: PortfolioState,
        proposed_qty: int,
        proposed_price: float,
        proposed_stop_loss: float | None = None,
        sector: str | None = None,
    ) -> tuple[bool, str, int]:
        """Validate and optionally reduce quantity.

        Returns: (approved, reason, adjusted_qty)
        """
        lim = self.limits
        if proposed_qty <= 0 or proposed_price <= 0:
            return False, "invalid_order_size", 0

        # 1. Daily loss kill switch.
        if portfolio.equity > 0:
            daily_loss_pct = abs(min(portfolio.daily_pnl, 0)) / portfolio.equity
            if daily_loss_pct >= lim.max_daily_loss_pct:
                return False, "daily_loss_limit", 0

        # 2. No-trade and confidence checks.
        if signal.no_trade_flag:
            return False, "no_trade_flag", 0
        if signal.confidence_score < lim.min_signal_confidence:
            return False, f"low_confidence={signal.confidence_score:.2f}", 0
        if signal.event_risk_score > lim.max_event_risk:
            return False, f"high_event_risk={signal.event_risk_score:.2f}", 0

        # 3. High-vol guardrail.
        if (
            signal.expected_volatility >= lim.high_vol_no_trade_threshold
            and signal.confidence_score < lim.high_vol_min_confidence
        ):
            return False, "high_vol_low_confidence", 0

        # 4. Per-day trade cap.
        if portfolio.daily_trades >= lim.max_daily_trades:
            return False, "max_daily_trades", 0

        # 5. Position count.
        if signal.signal_direction != SignalDirection.FLAT and portfolio.open_position_count >= lim.max_positions:
            return False, "max_positions_reached", 0

        # 6. Symbol cooldown + duplicate entry.
        if portfolio.in_cooldown(signal.instrument):
            return False, "symbol_cooldown", 0

        existing = portfolio.positions.get(signal.instrument)
        if signal.signal_direction == SignalDirection.LONG and existing and existing.quantity > 0:
            return False, "already_long", 0

        # 7. Momentum confirmation.
        if lim.require_momentum_confirm and not _momentum_confirms(signal):
            return False, "momentum_against", 0

        equity = max(portfolio.equity, 1.0)

        # 8. Capital-per-trade cap and per-position cap.
        proposed_value = proposed_qty * proposed_price
        max_trade_value = equity * min(lim.max_position_pct, lim.max_capital_per_trade_pct)
        if proposed_value > max_trade_value:
            proposed_qty = max(1, int(max_trade_value / proposed_price))
            proposed_value = proposed_qty * proposed_price

        # 9. Gross exposure cap.
        new_gross = portfolio.gross_exposure + proposed_value
        if new_gross > equity * lim.max_gross_exposure_pct:
            room = equity * lim.max_gross_exposure_pct - portfolio.gross_exposure
            if room <= 0:
                return False, "gross_exposure_limit", 0
            proposed_qty = max(1, int(room / proposed_price))
            proposed_value = proposed_qty * proposed_price

        # 10. Sector cap.
        signal_sector = sector or signal.sector or portfolio.sector_map.get(signal.instrument, "UNKNOWN")
        sector_exposure = portfolio.sector_exposure().get(signal_sector, 0.0) + proposed_value
        if sector_exposure > equity * lim.max_sector_exposure_pct:
            return False, f"sector_exposure_limit:{signal_sector}", 0

        # 11. Portfolio heat cap.
        heat = portfolio.portfolio_heat()
        if proposed_stop_loss is not None:
            risk_per_share = abs(proposed_price - proposed_stop_loss)
            if risk_per_share > 0:
                projected_heat = heat + (risk_per_share * proposed_qty) / equity
                if projected_heat > lim.max_portfolio_heat_pct:
                    heat_room = max(lim.max_portfolio_heat_pct - heat, 0.0) * equity
                    if heat_room <= 0:
                        return False, "portfolio_heat_limit", 0
                    proposed_qty = int(heat_room / max(risk_per_share, 1e-9))
                    if proposed_qty <= 0:
                        return False, "portfolio_heat_limit", 0

        # 12. Loss streak cooldown.
        if portfolio.daily_losses >= lim.max_loss_streak_trades:
            return False, "loss_streak_cooldown", 0

        # 13. Volatility circuit breaker.
        if signal.expected_volatility > lim.volatility_circuit_breaker:
            return False, f"vol_circuit_breaker={signal.expected_volatility:.3f}", 0

        return True, "approved", proposed_qty


# =====================================================================
#  Position sizing
# =====================================================================


def _risk_per_share(signal: TradingSignal, current_price: float, limits: RiskLimits) -> float:
    atr = float(signal.metadata.get("atr_14", 0.0)) if signal.metadata else 0.0
    atr_risk = atr * limits.atr_stop_multiplier if (limits.use_atr_stops and atr > 0) else 0.0
    pct_risk = current_price * limits.stop_loss_pct
    return max(atr_risk, pct_risk, current_price * 0.005)


def size_position(
    signal: TradingSignal,
    portfolio: PortfolioState,
    limits: RiskLimits,
    current_price: float,
    strategy_mode: StrategyMode = StrategyMode.AUTO,
) -> int:
    """Conservative sizing based on confidence, vol, regime, and risk heat."""
    if current_price <= 0:
        return 0

    mode = strategy_mode if strategy_mode != StrategyMode.AUTO else select_strategy_mode(signal)
    equity = max(portfolio.equity, 1.0)
    max_alloc = equity * min(limits.max_position_pct, limits.max_capital_per_trade_pct)

    # Confidence-weighted allocation.
    min_conf = limits.min_signal_confidence
    excess = max(signal.confidence_score - min_conf, 0.0)
    max_excess = max(1.0 - min_conf, 1e-6)
    conf_scale = min(0.25 + 0.75 * (excess / max_excess), 1.0)

    # Volatility-adjusted allocation.
    vol_adj = 1.0
    if signal.expected_volatility > 0.01:
        vol_adj = max(0.30, min(1.0, 0.22 / signal.expected_volatility))

    regime_adj = _regime_scale(signal.regime_label, limits)
    mode_adj = _strategy_scale(mode)

    loss_adj = 1.0
    if portfolio.consecutive_losses >= limits.loss_streak_half_size:
        loss_adj = 0.5

    heat = portfolio.portfolio_heat()
    heat_ratio = min(heat / max(limits.max_portfolio_heat_pct, 1e-9), 1.0)
    heat_adj = max(0.2, 1.0 - 0.7 * heat_ratio)

    alloc = max_alloc * conf_scale * vol_adj * regime_adj * mode_adj * loss_adj * heat_adj
    alloc = min(alloc, max_alloc, portfolio.cash * 0.95)

    qty = int(alloc / current_price)
    if qty <= 0:
        return 0

    # Risk-budget cap via portfolio heat.
    risk_room_value = max(limits.max_portfolio_heat_pct - heat, 0.0) * equity
    per_share_risk = _risk_per_share(signal, current_price, limits)
    qty_by_heat = int(risk_room_value / per_share_risk) if per_share_risk > 0 else qty
    if qty_by_heat <= 0:
        return 0

    return max(1, min(qty, qty_by_heat))


# =====================================================================
#  Stops
# =====================================================================


def _compute_stops(
    current_price: float,
    signal: TradingSignal,
    limits: RiskLimits,
    strategy_mode: StrategyMode,
) -> tuple[float, float, float]:
    """Return (stop_loss, take_profit, atr_at_entry)."""
    atr = float(signal.metadata.get("atr_14", 0.0)) if signal.metadata else 0.0

    stop_mult = limits.atr_stop_multiplier
    profit_mult = limits.atr_profit_multiplier
    if strategy_mode == StrategyMode.BREAKOUT:
        stop_mult *= 1.1
        profit_mult *= 1.25
    elif strategy_mode == StrategyMode.MEAN_REVERSION:
        stop_mult *= 0.9
        profit_mult *= 0.8
    elif strategy_mode == StrategyMode.LOW_VOL_TREND:
        stop_mult *= 0.95
        profit_mult *= 1.1

    if limits.use_atr_stops and atr > 0:
        stop_loss = round(current_price - atr * stop_mult, 2)
        take_profit = round(current_price + atr * profit_mult, 2)
    else:
        stop_loss = round(current_price * (1 - limits.stop_loss_pct), 2)
        take_profit = round(current_price * (1 + limits.take_profit_pct), 2)
        atr = 0.0

    min_sl = round(current_price * 0.99, 2)
    if stop_loss > min_sl:
        stop_loss = min_sl

    if take_profit <= current_price:
        take_profit = round(current_price * (1 + limits.take_profit_pct), 2)

    return stop_loss, take_profit, atr


# =====================================================================
#  Strategy engine
# =====================================================================


class StrategyEngine:
    """Single entry point for strategy decisions in all modes."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self.risk_gate = RiskGate(self.limits)
        self._bar_index = 0

    @property
    def bar_index(self) -> int:
        return self._bar_index

    @bar_index.setter
    def bar_index(self, value: int) -> None:
        self._bar_index = value

    def advance_bar(self, portfolio: PortfolioState) -> None:
        """Move engine state forward by one bar."""
        self._bar_index += 1
        portfolio.decrement_cooldowns()

    def rank_eligible_signals(
        self,
        signals: list[TradingSignal],
        portfolio: PortfolioState,
        prices: dict[str, float],
    ) -> list[TradingSignal]:
        """Rank incoming signals for capital allocation priority."""
        candidates: list[tuple[float, TradingSignal]] = []
        for signal in signals:
            if signal.signal_direction != SignalDirection.LONG:
                continue
            price = prices.get(signal.instrument)
            if price is None or price <= 0:
                continue
            if portfolio.in_cooldown(signal.instrument):
                continue

            mode = select_strategy_mode(signal)
            if not _mode_allows_signal(signal, mode):
                continue

            confidence = max(signal.confidence_score, signal.direction_probability)
            expected_edge = max(signal.expected_move, 0.0)
            regime_score = _regime_scale(signal.regime_label, self.limits)
            bonus = _strategy_rank_bonus(signal, mode)
            score = confidence * 0.55 + expected_edge * 3.0 + regime_score * 0.25 + bonus
            signal.ranking_score = float(score)
            candidates.append((score, signal))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [sig for _, sig in candidates]

    def rank_and_select_top_n(
        self,
        signals: list[TradingSignal],
        portfolio: PortfolioState,
        prices: dict[str, float],
        *,
        top_n: int | None = None,
        use_ranking_score: bool = True,
    ) -> list[TradingSignal]:
        """Select top-N signals by cross-sectional ranking score.

        When ``use_ranking_score=True`` (the new ranking pipeline path),
        signals are sorted purely by their pre-computed ``ranking_score``
        from the regime-aware ranking model. This bypasses the legacy
        composite score used in ``rank_eligible_signals()``.

        Parameters
        ----------
        signals : Pool of candidate signals for one date/bar.
        top_n : Max number of signals to return.  Falls back to
            ``self.limits.max_positions``.
        use_ranking_score : If True, sort by ``signal.ranking_score``
            (set by the ranking model) instead of the legacy composite score.
        """
        n = top_n or self.limits.max_positions
        candidates: list[tuple[float, TradingSignal]] = []

        for signal in signals:
            if signal.signal_direction != SignalDirection.LONG:
                continue
            price = prices.get(signal.instrument)
            if price is None or price <= 0:
                continue
            if portfolio.in_cooldown(signal.instrument):
                continue

            if use_ranking_score and hasattr(signal, "ranking_score") and signal.ranking_score is not None:
                score = float(signal.ranking_score)
            else:
                # Fall back to legacy composite score
                mode = select_strategy_mode(signal)
                if not _mode_allows_signal(signal, mode):
                    continue
                confidence = max(signal.confidence_score, signal.direction_probability)
                expected_edge = max(signal.expected_move, 0.0)
                regime_score = _regime_scale(signal.regime_label, self.limits)
                bonus = _strategy_rank_bonus(signal, mode)
                score = confidence * 0.55 + expected_edge * 3.0 + regime_score * 0.25 + bonus

            signal.ranking_score = float(score)
            candidates.append((score, signal))

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = [sig for _, sig in candidates[:n]]

        open_slots = max(self.limits.max_positions - portfolio.open_position_count, 0)
        return selected[:open_slots]

    def build_orders(
        self,
        signals: list[TradingSignal],
        portfolio: PortfolioState,
        prices: dict[str, float],
    ) -> list[OrderRequest]:
        """Ingest and rank predictions, then build orders conservatively."""
        orders: list[OrderRequest] = []

        # Always process explicit exits first.
        for signal in signals:
            if signal.signal_direction in (SignalDirection.FLAT, SignalDirection.SHORT):
                price = prices.get(signal.instrument)
                if price is None:
                    continue
                orders.extend(self.on_signal(signal, portfolio, price))

        open_slots = max(self.limits.max_positions - portfolio.open_position_count, 0)
        if open_slots <= 0:
            return orders

        ranked = self.rank_eligible_signals(signals, portfolio, prices)
        for signal in ranked[:open_slots]:
            price = prices.get(signal.instrument)
            if price is None:
                continue
            orders.extend(self.on_signal(signal, portfolio, price))

        return orders

    def on_signal(
        self,
        signal: TradingSignal,
        portfolio: PortfolioState,
        current_price: float,
    ) -> list[OrderRequest]:
        """Process one signal and return zero or more orders."""
        orders: list[OrderRequest] = []

        if signal.signal_direction == SignalDirection.FLAT:
            pos = portfolio.positions.get(signal.instrument)
            if pos and pos.is_open:
                orders.append(self._make_exit_order(pos, current_price, reason="signal_flat"))
            return orders

        if signal.signal_direction == SignalDirection.SHORT:
            pos = portfolio.positions.get(signal.instrument)
            if pos and pos.quantity > 0:
                orders.append(self._make_exit_order(pos, current_price, reason="signal_short"))
            return orders

        strategy_mode = select_strategy_mode(signal)
        if not _mode_allows_signal(signal, strategy_mode):
            return orders

        qty = size_position(
            signal,
            portfolio,
            self.limits,
            current_price,
            strategy_mode=strategy_mode,
        )
        if qty <= 0:
            return orders

        stop_loss, take_profit, atr = _compute_stops(
            current_price,
            signal,
            self.limits,
            strategy_mode,
        )

        approved, reason, adj_qty = self.risk_gate.approve(
            signal,
            portfolio,
            qty,
            current_price,
            proposed_stop_loss=stop_loss,
            sector=signal.sector,
        )
        if not approved or adj_qty <= 0:
            logger.debug("Signal rejected for %s: %s", signal.instrument, reason)
            return orders

        risk_per_share = abs(current_price - stop_loss)
        orders.append(
            OrderRequest(
                instrument=signal.instrument,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=adj_qty,
                stop_loss=stop_loss,
                take_profit=take_profit,
                trailing_stop_pct=self.limits.trailing_stop_pct,
                signal=signal,
                metadata={
                    "atr_at_entry": atr,
                    "strategy_mode": strategy_mode.value,
                    "sector": signal.sector,
                    "risk_per_share": risk_per_share,
                },
            )
        )
        return orders

    def check_exits(
        self,
        portfolio: PortfolioState,
        prices: dict[str, float],
    ) -> list[OrderRequest]:
        """Check all open positions for exits."""
        orders: list[OrderRequest] = []
        for instrument, pos in list(portfolio.positions.items()):
            if not pos.is_open or pos.quantity <= 0:
                continue

            price = prices.get(instrument)
            if price is None:
                continue

            pos.mark_to_market(price)
            self._apply_profit_protection(pos, price)

            partial_order = self._check_partial_tp(pos, price)
            if partial_order:
                orders.append(partial_order)
                continue

            reason = self._should_exit(pos, price)
            if reason:
                orders.append(self._make_exit_order(pos, price, reason))
        return orders

    def _apply_profit_protection(self, pos: Position, price: float) -> None:
        """Move stop to protect profits after +R progress."""
        if pos.stop_loss is None:
            return
        entry_risk = abs(pos.avg_entry_price - pos.stop_loss)
        if entry_risk <= 0:
            return

        r_multiple = pos.max_favorable_excursion / entry_risk
        if r_multiple < self.limits.profit_lock_trigger_r:
            return

        locked_price = pos.avg_entry_price + (pos.max_favorable_excursion * self.limits.profit_lock_fraction)
        if locked_price > pos.stop_loss:
            pos.stop_loss = round(locked_price, 2)

    def _check_partial_tp(self, pos: Position, price: float) -> OrderRequest | None:
        lim = self.limits
        if not lim.partial_tp_enabled or pos.partial_tp_done:
            return None
        if pos.original_quantity < 2:
            return None
        if pos.take_profit is None:
            return None

        tp_distance = pos.take_profit - pos.avg_entry_price
        if tp_distance <= 0:
            return None

        trigger_price = pos.avg_entry_price + tp_distance * lim.partial_tp_trigger_pct
        if price < trigger_price:
            return None

        sell_qty = max(1, int(pos.original_quantity * lim.partial_tp_fraction))
        sell_qty = min(sell_qty, pos.quantity)
        if sell_qty <= 0:
            return None

        pos.stop_loss = round(max(pos.avg_entry_price, pos.stop_loss or pos.avg_entry_price), 2)
        pos.partial_tp_done = True
        return OrderRequest(
            instrument=pos.instrument,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=sell_qty,
            metadata={"exit_reason": "partial_tp"},
        )

    def _should_exit(self, pos: Position, price: float) -> str | None:
        if pos.stop_loss and price <= pos.stop_loss:
            return "stop_loss"
        if pos.take_profit and price >= pos.take_profit:
            return "take_profit"
        if pos.trailing_stop_pct and pos.trailing_high > 0:
            trail_price = pos.trailing_high * (1 - pos.trailing_stop_pct)
            if price <= trail_price:
                return "trailing_stop"
        bars_held = self._bar_index - pos.entry_bar_index
        if bars_held >= self.limits.max_holding_bars:
            return "max_holding"
        return None

    def _make_exit_order(self, pos: Position, _price: float, reason: str) -> OrderRequest:
        metadata = {"exit_reason": reason}
        if reason in {"stop_loss", "trailing_stop"}:
            metadata["cooldown_bars"] = self.limits.symbol_cooldown_bars
        return OrderRequest(
            instrument=pos.instrument,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=abs(pos.quantity),
            metadata=metadata,
        )
