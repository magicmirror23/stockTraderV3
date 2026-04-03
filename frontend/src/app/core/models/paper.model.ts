/** Paper trading models — kept in core/models for shared access */

export interface PaperAccount {
  account_id: string;
  cash: number;
  equity: number;
  created_at: string;
}

export interface EquityPoint {
  date: string;
  equity: number;
}

export interface AccountMetrics {
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  total_trades: number;
  net_pnl: number;
}
