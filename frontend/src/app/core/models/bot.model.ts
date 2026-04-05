/** Auto-trading bot models */

export interface BotStatus {
  state?: string;
  config?: Record<string, unknown>;
  running: boolean;
  paused: boolean;
  consent_pending: boolean;
  auto_resume_in: number | null;
  watchlist: string[];
  min_confidence: number;
  max_positions: number;
  position_size: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  cycle_interval: number;
  cycle_count: number;
  last_cycle: string | null;
  active_positions: number;
  available_balance?: number;
  total_equity?: number;
  net_pnl?: number;
  positions: Record<string, any>;
  trades_today: any[];
  total_pnl: number;
  total_charges?: number;
  errors: string[];
  error_message?: string | null;
}

export interface BotConfig {
  watchlist?: string[];
  min_confidence?: number;
  max_positions?: number;
  position_size?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  cycle_interval?: number;
}
