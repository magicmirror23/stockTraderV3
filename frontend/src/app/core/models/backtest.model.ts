/** Backtest models */

export interface BacktestRunRequest {
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  strategy: string;
}

export interface BacktestRunResponse {
  job_id: string;
  status: string;
  submitted_at: string;
}

export interface BacktestTrade {
  date: string;
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  pnl: number;
}

export interface BacktestResults {
  job_id: string;
  status: string;
  tickers: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_value: number;
  total_return_pct: number;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  trades: BacktestTrade[];
  completed_at: string | null;
}
