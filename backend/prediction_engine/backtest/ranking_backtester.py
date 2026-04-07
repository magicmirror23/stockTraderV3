"""Cross-sectional ranking backtester.

Simulates a top-N portfolio selection strategy:
1. Each rebalance date, rank all symbols by predicted score.
2. Select top-N symbols to hold for `horizon` bars.
3. Equal-weight the portfolio across selected symbols.
4. Compute Sharpe, Sortino, max drawdown, win rate, total return.

This module is intentionally lightweight -- it does not use the full
event-driven backtester or execution adapter.  For detailed fills and
slippage modelling, use the event-driven path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RankingBacktestConfig:
    """Parameters for the ranking backtester."""

    top_n: int = 10
    horizon: int = 3
    rebalance_every: int = 1  # rebalance every N trading days
    initial_capital: float = 1_000_000.0
    commission_bps: float = 5.0  # round-trip cost in bps
    slippage_bps: float = 3.0  # per-side slippage estimate


@dataclass
class RankingBacktestResult:
    """Return container from a ranking backtest."""

    daily_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    trades: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def run_ranking_backtest(
    scored_frame: pd.DataFrame,
    *,
    score_col: str = "ranking_score",
    return_col: str = "target_horizon_return",
    date_col: str = "date",
    ticker_col: str = "ticker",
    config: RankingBacktestConfig | None = None,
) -> RankingBacktestResult:
    """Run a cross-sectional ranking backtest.

    Parameters
    ----------
    scored_frame : DataFrame with at least [date, ticker, score_col, return_col].
    score_col : Column name with the predicted ranking score.
    return_col : Column name with the realised forward return for the horizon.
    config : Backtest configuration.

    Returns
    -------
    RankingBacktestResult with equity curve, daily returns, and summary.
    """
    if config is None:
        config = RankingBacktestConfig()

    df = scored_frame[[date_col, ticker_col, score_col, return_col]].copy()
    df = df.dropna(subset=[score_col, return_col])
    if df.empty:
        logger.warning("Ranking backtest: no valid rows after dropping NaN.")
        return RankingBacktestResult(summary={"error": "no valid rows"})

    df = df.sort_values(date_col).reset_index(drop=True)
    dates = sorted(df[date_col].unique())

    cost_per_trade = (config.commission_bps + 2 * config.slippage_bps) / 10_000.0

    daily_returns: list[float] = []
    daily_dates: list[Any] = []
    all_trades: list[dict[str, Any]] = []
    total_winning = 0
    total_trades = 0

    rebal_counter = 0
    for date in dates:
        rebal_counter += 1
        if rebal_counter % config.rebalance_every != 0:
            continue

        day_df = df[df[date_col] == date]
        if day_df.empty or len(day_df) < 3:
            continue

        top = day_df.nlargest(min(config.top_n, len(day_df)), score_col)
        n_selected = len(top)
        if n_selected == 0:
            continue

        # Equal-weight portfolio return for this rebalance period
        raw_returns = top[return_col].values
        portfolio_return = float(np.nanmean(raw_returns))

        # Subtract transaction costs (proportional to number of positions)
        net_return = portfolio_return - cost_per_trade

        daily_returns.append(net_return)
        daily_dates.append(date)

        # Track individual trades
        for _, row in top.iterrows():
            ret = float(row[return_col])
            total_trades += 1
            if ret > 0:
                total_winning += 1
            all_trades.append({
                "date": str(date),
                "ticker": str(row[ticker_col]),
                "score": float(row[score_col]),
                "return": ret,
                "net_return": ret - cost_per_trade,
            })

    if not daily_returns:
        logger.warning("Ranking backtest: no trading days generated.")
        return RankingBacktestResult(summary={"error": "no trading days"})

    ret_series = pd.Series(daily_returns, index=pd.to_datetime(daily_dates), name="daily_return")
    equity = config.initial_capital * (1.0 + ret_series).cumprod()

    # Summary metrics
    total_return = float(equity.iloc[-1] / config.initial_capital - 1.0)
    n_days = len(daily_returns)
    mean_daily = float(ret_series.mean())
    std_daily = float(ret_series.std()) if n_days > 1 else 0.0

    # Sharpe (annualised, 252 trading days)
    sharpe = float(mean_daily / std_daily * np.sqrt(252)) if std_daily > 1e-9 else 0.0

    # Sortino
    downside = ret_series[ret_series < 0]
    downside_std = float(downside.std()) if len(downside) > 1 else 0.0
    sortino = float(mean_daily / downside_std * np.sqrt(252)) if downside_std > 1e-9 else 0.0

    # Max drawdown
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    max_dd = float(drawdown.min())

    win_rate = float(total_winning / max(total_trades, 1))

    summary = {
        "total_return_pct": round(total_return * 100, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "win_rate": round(win_rate, 4),
        "total_trades": total_trades,
        "winning_trades": total_winning,
        "trading_days": n_days,
        "avg_daily_return_pct": round(mean_daily * 100, 6),
        "initial_capital": config.initial_capital,
        "final_equity": round(float(equity.iloc[-1]), 2),
        "top_n": config.top_n,
        "horizon": config.horizon,
        "rebalance_every": config.rebalance_every,
        "commission_bps": config.commission_bps,
        "slippage_bps": config.slippage_bps,
    }

    logger.info(
        "Ranking backtest: return=%.2f%% sharpe=%.2f sortino=%.2f drawdown=%.2f%% trades=%d win_rate=%.2f%%",
        total_return * 100, sharpe, sortino, max_dd * 100, total_trades, win_rate * 100,
    )

    return RankingBacktestResult(
        daily_returns=ret_series,
        equity_curve=equity,
        trades=all_trades,
        summary=summary,
    )
