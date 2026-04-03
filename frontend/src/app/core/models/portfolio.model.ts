/** Portfolio analytics models */

export interface PortfolioMetrics {
  total_equity: number;
  cash: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_charges: number;
  net_pnl: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  max_drawdown_pct: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  avg_win: number;
  avg_loss: number;
  total_exposure: number;
  exposure_pct: number;
  by_strategy: Record<string, number>;
  by_symbol: Record<string, number>;
  by_sector: Record<string, number>;
  portfolio_delta: number;
  portfolio_gamma: number;
  portfolio_theta: number;
  portfolio_vega: number;
}
