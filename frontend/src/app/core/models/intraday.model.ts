/** Intraday trading stack models */

export interface IntradaySignal {
  symbol: string;
  action: string;
  confidence: number;
  expected_return: number;
  score: number;
  model_version: string;
  features_used: number;
  signal_type: string;
  eligible: boolean;
  rejection_reason: string;
}

export interface IntradayModelStatus {
  loaded: boolean;
  version: string;
  model_name: string;
  target_type: string;
  horizon_bars: number;
  n_features: number;
  metrics: Record<string, number>;
}

export interface IntradayOptionSignal {
  symbol: string;
  signal_type: string;
  direction: string;
  confidence: number;
  underlying_price: number;
  entry_strike: number;
  exit_strike: number;
  option_type: string;
  expiry: string;
  max_loss: number;
  max_profit: number;
  breakeven: number;
  risk_reward: number;
  volatility_regime: string;
  reasoning: string[];
  eligible: boolean;
  rejection_reason: string;
}

export interface IntradayExecutionStats {
  open_positions: number;
  total_closed: number;
  total_pnl: number;
  win_rate: number;
  profit_factor: number;
  wins: number;
  losses: number;
  trades_today: number;
}

export interface OpenPosition {
  order_id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  unrealized_pnl: number;
  bars_held: number;
  confidence: number;
  signal_type: string;
}

export interface SupervisorStatus {
  state: string;
  pause_reason: string | null;
  daily_pnl: number;
  peak_equity: number;
  current_equity: number;
  drawdown_pct: number;
  open_positions: Record<string, number>;
  total_open: number;
  cooldowns: Record<string, number>;
  trades_last_minute: number;
  pause_history: Array<Record<string, unknown>>;
}

export interface IntradayTrainStatus {
  state: string;
  started_at?: string;
  config?: Record<string, unknown>;
  error?: string;
}
