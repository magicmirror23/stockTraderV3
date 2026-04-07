# Backtesting logic

"""Event-driven backtester with strict parity and anti-leakage controls.

This module uses the same shared strategy engine and execution adapter used by
paper/live paths. Backtests differ only by:
1) historical market-data source
2) event replay loop
3) deterministic execution simulation settings
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backend.shared.execution import (
    BacktestExecutor,
    SimulationConfig,
    apply_fill_to_portfolio,
)
from backend.shared.leakage import (
    LeakageError,
    verify_backtest_no_lookahead,
    verify_feature_timestamps,
)
from backend.shared.schemas import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    PortfolioState,
    Position,
    RegimeLabel,
    RiskLimits,
    SignalDirection,
    TradeResult,
    TradingSignal,
)
from backend.shared.strategy_engine import StrategyEngine

logger = logging.getLogger(__name__)

STORAGE_DIR = Path(__file__).resolve().parents[3] / "storage" / "backtests"


# -----------------------------------------------------------------------
# API-compat dataclasses
# -----------------------------------------------------------------------


@dataclass
class ExecutionConfig:
    """Configurable execution model for the backtester."""

    slippage_pct: float = 0.001
    fill_probability: float = 0.98
    use_angel_charges: bool = True
    trade_type: str = "intraday"
    commission_per_trade: float = 20.0
    latency_ms: int = 50
    partial_fill_prob: float = 0.0
    execution_delay_bars: int = 1


@dataclass
class Trade:
    """Single trade event record for JSON serialization."""

    date: str
    ticker: str
    side: str
    quantity: int
    price: float
    pnl: float = 0.0
    charges: float = 0.0
    exit_reason: str = ""
    signal_time: str | None = None
    execution_time: str | None = None
    sector: str = "Unknown"
    regime: str = "unknown"


@dataclass
class BacktestResult:
    job_id: str
    status: str
    tickers: list[str]
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_pct: float | None = None
    cagr_pct: float | None = None
    total_charges: float = 0.0
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    expectancy: float | None = None
    total_trades: int = 0
    no_trade_count: int = 0
    rejection_count: int = 0
    turnover: float = 0.0
    avg_holding_bars: float | None = None
    median_holding_bars: float | None = None
    win_loss_distribution: dict = field(default_factory=dict)
    metrics_by_symbol: dict = field(default_factory=dict)
    metrics_by_sector: dict = field(default_factory=dict)
    metrics_by_regime: dict = field(default_factory=dict)
    equity_curve: list[dict] = field(default_factory=list)
    drawdown_curve: list[dict] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    walk_forward: dict = field(default_factory=dict)
    completed_at: str | None = None


@dataclass
class _PendingOrder:
    event_id: int
    order: OrderRequest
    decision_ts: pd.Timestamp
    execute_bar_idx: int
    decision_bar_idx: int
    kind: str  # entry | exit


class Backtester:
    """Event-driven backtester using shared strategy/risk/execution modules."""

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        risk_limits: RiskLimits | None = None,
    ) -> None:
        self.config = config or ExecutionConfig()
        self.risk_limits = risk_limits or RiskLimits()

        sim_config = SimulationConfig(
            slippage_pct=self.config.slippage_pct,
            fill_probability=self.config.fill_probability,
            use_angel_charges=self.config.use_angel_charges,
            trade_type=self.config.trade_type,
            commission_flat=self.config.commission_per_trade,
            latency_ms=self.config.latency_ms,
            partial_fill_prob=self.config.partial_fill_prob,
        )
        self.executor = BacktestExecutor(sim_config)
        self.strategy = StrategyEngine(self.risk_limits)

    @staticmethod
    def _infer_regime(
        adx: float,
        vol: float,
        rsi: float,
        dist_sma50: float,
    ) -> RegimeLabel:
        if vol > 0.40:
            if rsi < 30:
                return RegimeLabel.CRASH
            return RegimeLabel.HIGH_VOLATILITY
        if adx > 25:
            if dist_sma50 > 0.02:
                return RegimeLabel.TRENDING_UP
            if dist_sma50 < -0.02:
                return RegimeLabel.TRENDING_DOWN
        if vol < 0.12:
            return RegimeLabel.LOW_VOLATILITY
        return RegimeLabel.RANGE_BOUND

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        try:
            out = float(value)
            if math.isnan(out) or math.isinf(out):
                return default
            return out
        except Exception:
            return default

    @staticmethod
    def _prepare_predictions(predictions_df: pd.DataFrame) -> pd.DataFrame:
        required = {"date", "ticker", "action", "confidence"}
        missing = required.difference(predictions_df.columns)
        if missing:
            raise ValueError(f"Predictions missing required columns: {sorted(missing)}")

        df = predictions_df.copy()
        df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

        if "signal_date" in df.columns:
            df["signal_date"] = pd.to_datetime(df["signal_date"]).dt.tz_localize(None)
        else:
            df["signal_date"] = df["date"]

        bad_rows = df["signal_date"] > df["date"]
        if bad_rows.any():
            sample = df.loc[bad_rows, ["ticker", "signal_date", "date"]].head(5).to_dict(orient="records")
            raise LeakageError(
                f"Found prediction rows with signal_date > execution date: {sample}"
            )

        # Guard against accidental forward-looking columns.
        verify_feature_timestamps(df, decision_time_col="signal_date")

        return df.sort_values(["signal_date", "ticker", "date"]).reset_index(drop=True)

    @staticmethod
    def _prepare_prices(price_df: pd.DataFrame) -> pd.DataFrame:
        required = {"Date", "ticker", "Close"}
        missing = required.difference(price_df.columns)
        if missing:
            raise ValueError(f"Price data missing required columns: {sorted(missing)}")

        df = price_df.copy()
        df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
        df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Date", "ticker", "Close"])
        df = df.drop_duplicates(subset=["Date", "ticker"], keep="last")
        return df.sort_values(["Date", "ticker"]).reset_index(drop=True)

    def _to_signal(self, pred: pd.Series) -> TradingSignal:
        action = str(pred.get("action", "hold")).strip().lower()
        if action == "buy":
            direction = SignalDirection.LONG
        elif action == "sell":
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        confidence = self._safe_float(pred.get("confidence", 0.5), 0.5)
        vol = self._safe_float(pred.get("volatility_20", 0.20), 0.20) or 0.20
        atr = self._safe_float(pred.get("atr_14", 0.0), 0.0)
        momentum = self._safe_float(pred.get("momentum_10", 0.0), 0.0)
        ema_cross = self._safe_float(pred.get("ema_crossover", 0.0), 0.0)
        adx = self._safe_float(pred.get("adx_14", 0.0), 0.0)
        rsi = self._safe_float(pred.get("rsi_14", 50.0), 50.0) or 50.0
        dist_sma50 = self._safe_float(pred.get("distance_sma50", 0.0), 0.0)
        regime = self._infer_regime(adx, vol, rsi, dist_sma50)
        sector = str(pred.get("sector", "Unknown") or "Unknown")
        industry = str(pred.get("industry", "Unknown") or "Unknown")

        signal_ts = pd.Timestamp(pred["signal_date"]).to_pydatetime()
        return TradingSignal(
            instrument=str(pred["ticker"]).upper(),
            timestamp=signal_ts,
            timeframe="1d",
            signal_direction=direction,
            direction_probability=max(confidence, 1 - confidence),
            expected_move=(confidence - 0.5) * vol * 2,
            expected_volatility=vol,
            confidence_score=confidence,
            regime_label=regime,
            no_trade_flag=(direction == SignalDirection.FLAT),
            model_version="backtest",
            sector=sector,
            industry=industry,
            metadata={
                "atr_14": atr,
                "momentum_10": momentum,
                "ema_crossover": ema_cross,
                "adx_14": adx,
                "rsi_14": rsi,
            },
        )

    def _schedule_order(
        self,
        queue: list[_PendingOrder],
        *,
        event_id: int,
        order: OrderRequest,
        decision_ts: pd.Timestamp,
        decision_bar_idx: int,
        execute_bar_idx: int,
        kind: str,
    ) -> None:
        queue.append(
            _PendingOrder(
                event_id=event_id,
                order=order,
                decision_ts=decision_ts,
                execute_bar_idx=execute_bar_idx,
                decision_bar_idx=decision_bar_idx,
                kind=kind,
            )
        )

    def run(
        self,
        predictions_df: pd.DataFrame,
        price_df: pd.DataFrame,
        initial_capital: float = 100_000.0,
        job_id: str | None = None,
    ) -> BacktestResult:
        """Run an event-driven backtest with strict decision/execution separation."""

        job_id = job_id or str(uuid.uuid4())
        preds = self._prepare_predictions(predictions_df)
        prices_df = self._prepare_prices(price_df)
        verify_backtest_no_lookahead(
            signals_df=preds,
            price_df=prices_df,
            signal_date_col="signal_date",
            price_date_col="Date",
        )

        calendar = sorted(pd.to_datetime(prices_df["Date"]).unique())
        if not calendar:
            raise ValueError("Price calendar is empty.")

        delay_bars = max(1, int(self.config.execution_delay_bars))
        last_bar_idx = len(calendar) - 1

        portfolio = PortfolioState(
            cash=initial_capital,
            execution_mode=ExecutionMode.BACKTEST,
        )

        by_decision_date: dict[pd.Timestamp, pd.DataFrame] = {
            k: g.copy() for k, g in preds.groupby("signal_date", sort=True)
        }
        by_price_date: dict[pd.Timestamp, pd.DataFrame] = {
            k: g.copy() for k, g in prices_df.groupby("Date", sort=True)
        }

        pending: list[_PendingOrder] = []
        pending_entry_symbols: set[str] = set()
        pending_exit_symbols: set[str] = set()
        event_seq = 0

        trades: list[Trade] = []
        completed_trades: list[TradeResult] = []
        equity_points: list[float] = []
        equity_curve: list[dict] = []
        drawdown_curve: list[dict] = []

        no_trade_count = 0
        rejection_count = 0
        turnover_value = 0.0
        running_peak: float | None = None

        for bar_idx, bar_date in enumerate(calendar):
            bar_ts = pd.Timestamp(bar_date)
            self.strategy.bar_index = bar_idx
            day_prices = by_price_date.get(bar_ts)
            if day_prices is None or day_prices.empty:
                continue

            px = {
                row["ticker"]: self._safe_float(row["Close"], 0.0)
                for _, row in day_prices.iterrows()
                if self._safe_float(row["Close"], 0.0) > 0
            }
            if not px:
                continue

            # Reset daily counters for this bar.
            portfolio.daily_pnl = 0.0
            portfolio.daily_trades = 0
            portfolio.daily_losses = 0

            # -----------------------------------------------------------
            # 1) Execute queued orders whose execution time has arrived
            # -----------------------------------------------------------
            due_events = [evt for evt in pending if evt.execute_bar_idx <= bar_idx]
            pending = [evt for evt in pending if evt.execute_bar_idx > bar_idx]
            due_events.sort(key=lambda evt: (evt.execute_bar_idx, evt.event_id))

            for evt in due_events:
                order = evt.order
                instrument = order.instrument
                market_price = px.get(instrument)
                if market_price is None or market_price <= 0:
                    rejection_count += 1
                    if evt.kind == "entry":
                        pending_entry_symbols.discard(instrument)
                    else:
                        pending_exit_symbols.discard(instrument)
                    continue

                state = self.executor.submit_order(
                    order,
                    portfolio,
                    market_price,
                    timestamp=bar_ts.to_pydatetime(),
                )
                if state.status in {OrderStatus.FILLED, OrderStatus.PARTIAL}:
                    for fill in state.fills:
                        turnover_value += fill.price * fill.quantity
                        result = apply_fill_to_portfolio(
                            fill,
                            portfolio,
                            order,
                            self.executor,
                            bar_idx,
                        )
                        trade_row = Trade(
                            date=str(bar_ts.date()),
                            ticker=instrument,
                            side=order.side.value,
                            quantity=int(fill.quantity),
                            price=round(fill.price, 2),
                            pnl=round(result.pnl, 2) if result else 0.0,
                            charges=round(result.charges, 2) if result else 0.0,
                            exit_reason=str(order.metadata.get("exit_reason", "")),
                            signal_time=evt.decision_ts.isoformat(),
                            execution_time=fill.timestamp.isoformat(),
                            sector=str((order.signal.sector if order.signal else order.metadata.get("sector", "Unknown")) or "Unknown"),
                            regime=str((order.signal.regime_label.value if order.signal else "unknown")),
                        )
                        trades.append(trade_row)
                        if result is not None:
                            completed_trades.append(result)
                else:
                    rejection_count += 1

                if evt.kind == "entry":
                    pending_entry_symbols.discard(instrument)
                else:
                    pending_exit_symbols.discard(instrument)

            # -----------------------------------------------------------
            # 2) Generate and schedule exits from open positions
            # -----------------------------------------------------------
            exit_orders = self.strategy.check_exits(portfolio, px)
            for order in exit_orders:
                instrument = order.instrument
                if instrument in pending_exit_symbols:
                    continue
                execute_idx = min(bar_idx + delay_bars, last_bar_idx)
                event_seq += 1
                self._schedule_order(
                    pending,
                    event_id=event_seq,
                    order=order,
                    decision_ts=bar_ts,
                    decision_bar_idx=bar_idx,
                    execute_bar_idx=execute_idx,
                    kind="exit",
                )
                pending_exit_symbols.add(instrument)

            # -----------------------------------------------------------
            # 3) Ingest model decisions at this decision timestamp
            # -----------------------------------------------------------
            day_preds = by_decision_date.get(bar_ts)
            day_signals: list[TradingSignal] = []
            if day_preds is not None and not day_preds.empty:
                for _, row in day_preds.iterrows():
                    signal = self._to_signal(row)
                    if signal.no_trade_flag:
                        no_trade_count += 1
                        continue
                    day_signals.append(signal)

            entry_orders = self.strategy.build_orders(day_signals, portfolio, px)
            if not entry_orders:
                rejection_count += sum(1 for s in day_signals if s.signal_direction != SignalDirection.FLAT)

            for order in entry_orders:
                instrument = order.instrument
                if order.side == OrderSide.BUY and instrument in pending_entry_symbols:
                    continue
                if order.side == OrderSide.SELL and instrument in pending_exit_symbols:
                    continue

                execute_idx = bar_idx + delay_bars
                # Cannot execute beyond available future bars.
                if execute_idx > last_bar_idx:
                    rejection_count += 1
                    continue

                event_seq += 1
                kind = "entry" if order.side == OrderSide.BUY else "exit"
                self._schedule_order(
                    pending,
                    event_id=event_seq,
                    order=order,
                    decision_ts=bar_ts,
                    decision_bar_idx=bar_idx,
                    execute_bar_idx=execute_idx,
                    kind=kind,
                )
                if kind == "entry":
                    pending_entry_symbols.add(instrument)
                else:
                    pending_exit_symbols.add(instrument)

            # -----------------------------------------------------------
            # 4) Mark-to-market and capture analytics snapshots
            # -----------------------------------------------------------
            for instrument, pos in portfolio.positions.items():
                if pos.is_open and instrument in px:
                    pos.mark_to_market(px[instrument])

            eq = float(portfolio.equity)
            equity_points.append(eq)
            equity_curve.append(
                {
                    "date": str(bar_ts.date()),
                    "equity": round(eq, 2),
                    "cash": round(float(portfolio.cash), 2),
                    "gross_exposure": round(float(portfolio.gross_exposure), 2),
                    "open_positions": int(portfolio.open_position_count),
                }
            )

            running_peak = eq if running_peak is None else max(running_peak, eq)
            drawdown_pct = 0.0 if running_peak <= 0 else ((running_peak - eq) / running_peak) * 100
            drawdown_curve.append(
                {
                    "date": str(bar_ts.date()),
                    "drawdown_pct": round(float(drawdown_pct), 4),
                }
            )

            self.strategy.advance_bar(portfolio)

        # Force-close anything still open at the final bar close.
        final_ts = pd.Timestamp(calendar[-1])
        final_prices_df = by_price_date.get(final_ts, pd.DataFrame())
        final_px = {
            row["ticker"]: self._safe_float(row["Close"], 0.0)
            for _, row in final_prices_df.iterrows()
            if self._safe_float(row["Close"], 0.0) > 0
        }
        for instrument, pos in list(portfolio.positions.items()):
            if not pos.is_open or pos.quantity <= 0:
                continue
            mkt = final_px.get(instrument)
            if mkt is None or mkt <= 0:
                continue
            order = self.strategy._make_exit_order(pos, mkt, "end_of_backtest")
            state = self.executor.submit_order(
                order,
                portfolio,
                mkt,
                timestamp=final_ts.to_pydatetime(),
            )
            if state.status in {OrderStatus.FILLED, OrderStatus.PARTIAL}:
                for fill in state.fills:
                    turnover_value += fill.price * fill.quantity
                    result = apply_fill_to_portfolio(
                        fill,
                        portfolio,
                        order,
                        self.executor,
                        len(calendar),
                    )
                    trade_row = Trade(
                        date=str(final_ts.date()),
                        ticker=instrument,
                        side=order.side.value,
                        quantity=int(fill.quantity),
                        price=round(fill.price, 2),
                        pnl=round(result.pnl, 2) if result else 0.0,
                        charges=round(result.charges, 2) if result else 0.0,
                        exit_reason="end_of_backtest",
                        signal_time=final_ts.isoformat(),
                        execution_time=fill.timestamp.isoformat(),
                        sector=str(pos.sector or "Unknown"),
                        regime="unknown",
                    )
                    trades.append(trade_row)
                    if result is not None:
                        completed_trades.append(result)

        result = self._build_result(
            job_id=job_id,
            predictions_df=preds,
            calendar=calendar,
            initial_capital=initial_capital,
            portfolio=portfolio,
            completed_trades=completed_trades,
            trades=trades,
            equity_points=equity_points,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            no_trade_count=no_trade_count,
            rejection_count=rejection_count,
            turnover_value=turnover_value,
        )
        self._save_result(result)
        return result

    def _build_result(
        self,
        *,
        job_id: str,
        predictions_df: pd.DataFrame,
        calendar: list[pd.Timestamp],
        initial_capital: float,
        portfolio: PortfolioState,
        completed_trades: list[TradeResult],
        trades: list[Trade],
        equity_points: list[float],
        equity_curve: list[dict],
        drawdown_curve: list[dict],
        no_trade_count: int,
        rejection_count: int,
        turnover_value: float,
    ) -> BacktestResult:
        final_value = float(portfolio.equity)
        total_return = (final_value / initial_capital - 1.0) * 100.0 if initial_capital > 0 else 0.0

        sharpe = self._sharpe(equity_points)
        sortino = self._sortino(equity_points)
        max_dd = self._max_drawdown(equity_points)
        cagr = self._cagr(initial_capital, final_value, len(calendar))

        pnls = [float(t.pnl) for t in completed_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = (len(wins) / len(pnls) * 100) if pnls else None
        avg_win = (sum(wins) / len(wins)) if wins else None
        avg_loss = (sum(losses) / len(losses)) if losses else None
        expectancy = (sum(pnls) / len(pnls)) if pnls else None

        hold_bars = [int(t.holding_bars) for t in completed_trades]
        avg_hold = (sum(hold_bars) / len(hold_bars)) if hold_bars else None
        med_hold = float(pd.Series(hold_bars).median()) if hold_bars else None

        win_loss_distribution = {
            "wins": len(wins),
            "losses": len(losses),
            "flat": len([p for p in pnls if p == 0]),
            "largest_win": round(max(wins), 2) if wins else 0.0,
            "largest_loss": round(min(losses), 2) if losses else 0.0,
            "profit_factor": round((sum(wins) / abs(sum(losses))) if losses else float("inf"), 4) if wins else 0.0,
        }

        metrics_by_symbol = self._group_trade_metrics(trades, key_field="ticker")
        metrics_by_sector = self._group_trade_metrics(trades, key_field="sector")
        metrics_by_regime = self._group_trade_metrics(trades, key_field="regime")

        turnover = turnover_value / max(initial_capital, 1.0)

        return BacktestResult(
            job_id=job_id,
            status="completed",
            tickers=sorted({str(v).upper() for v in predictions_df["ticker"].tolist()}),
            start_date=str(pd.Timestamp(calendar[0]).date()),
            end_date=str(pd.Timestamp(calendar[-1]).date()),
            initial_capital=initial_capital,
            final_value=round(final_value, 2),
            total_return_pct=round(total_return, 4),
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=max_dd,
            cagr_pct=cagr,
            total_charges=round(float(portfolio.total_commission), 2),
            win_rate=round(win_rate, 2) if win_rate is not None else None,
            avg_win=round(avg_win, 2) if avg_win is not None else None,
            avg_loss=round(avg_loss, 2) if avg_loss is not None else None,
            expectancy=round(expectancy, 2) if expectancy is not None else None,
            total_trades=len(completed_trades),
            no_trade_count=int(no_trade_count),
            rejection_count=int(rejection_count),
            turnover=round(turnover, 6),
            avg_holding_bars=round(avg_hold, 3) if avg_hold is not None else None,
            median_holding_bars=round(med_hold, 3) if med_hold is not None else None,
            win_loss_distribution=win_loss_distribution,
            metrics_by_symbol=metrics_by_symbol,
            metrics_by_sector=metrics_by_sector,
            metrics_by_regime=metrics_by_regime,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            trades=trades,
            # Use RFC3339 UTC form without duplicating timezone suffix.
            completed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    @staticmethod
    def _group_trade_metrics(trades: list[Trade], *, key_field: str) -> dict:
        grouped: dict[str, list[Trade]] = defaultdict(list)
        for trade in trades:
            grouped[str(getattr(trade, key_field, "Unknown") or "Unknown")].append(trade)

        out: dict[str, dict] = {}
        for key, rows in grouped.items():
            pnls = [float(r.pnl) for r in rows if float(r.pnl) != 0.0]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            out[key] = {
                "trades": int(len(rows)),
                "round_trips": int(len(pnls)),
                "pnl": round(sum(pnls), 2),
                "win_rate": round((len(wins) / len(pnls) * 100), 2) if pnls else None,
                "avg_pnl": round((sum(pnls) / len(pnls)), 4) if pnls else None,
                "profit_factor": round((sum(wins) / abs(sum(losses))), 4) if losses else (float("inf") if wins else 0.0),
            }
        return out

    @staticmethod
    def _sharpe(values: list[float], risk_free: float = 0.0) -> float | None:
        if len(values) < 2:
            return None
        rets = pd.Series(values).pct_change().dropna()
        if rets.empty or float(rets.std()) == 0.0:
            return None
        return round(float((rets.mean() - risk_free) / rets.std() * math.sqrt(252)), 6)

    @staticmethod
    def _sortino(values: list[float], risk_free: float = 0.0) -> float | None:
        if len(values) < 2:
            return None
        rets = pd.Series(values).pct_change().dropna()
        down = rets[rets < 0]
        if down.empty or float(down.std()) == 0.0:
            return None
        return round(float((rets.mean() - risk_free) / down.std() * math.sqrt(252)), 6)

    @staticmethod
    def _max_drawdown(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        peak = values[0]
        max_dd = 0.0
        for val in values:
            peak = max(peak, val)
            if peak <= 0:
                continue
            max_dd = max(max_dd, (peak - val) / peak)
        return round(max_dd * 100.0, 6)

    @staticmethod
    def _cagr(initial: float, final: float, bars: int) -> float | None:
        if initial <= 0 or final <= 0 or bars <= 0:
            return None
        years = bars / 252.0
        if years <= 0:
            return None
        return round(((final / initial) ** (1 / years) - 1) * 100.0, 6)

    @staticmethod
    def _save_result(result: BacktestResult) -> Path:
        job_dir = STORAGE_DIR / result.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "results.json"
        path.write_text(json.dumps(asdict(result), indent=2, default=str))
        logger.info("Backtest results saved -> %s", path)
        return path

    @staticmethod
    def load_result(job_id: str) -> dict | None:
        path = STORAGE_DIR / job_id / "results.json"
        if path.exists():
            return json.loads(path.read_text())
        return None
