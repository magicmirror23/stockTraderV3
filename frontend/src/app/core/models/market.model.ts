/** Market data models */

export interface MarketStatus {
  phase: 'pre_open' | 'open' | 'post_close' | 'closed' | 'holiday' | 'weekend';
  message: string;
  ist_now: string;
  next_event: string;
  next_event_time: string;
  seconds_to_next: number;
  is_trading_day: boolean;
}

export interface AccountProfile {
  status: string;
  message: string;
  name?: string;
  client_id?: string;
  email?: string;
  phone?: string;
  broker?: string;
  balance?: number;
  net?: number;
  available_margin?: number;
  utilized_margin?: number;
  credentials_set?: Record<string, boolean>;
}

export interface LiveTick {
  symbol: string;
  timestamp: string;
  price: number;
  volume: number;
  bid: number | null;
  ask: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  feed_mode?: string;
}

export interface WatchlistItem extends LiveTick {
  sparkline: number[];
}

export interface FeedStatus {
  feed_mode: string;
  available: boolean;
  authenticated?: boolean;
  connected?: boolean;
  symbols_streaming?: number;
  tokens_resolved?: number;
  tick_count?: number;
  error?: string | null;
}

export interface MarketOverview {
  gainers: LiveTick[];
  losers: LiveTick[];
  volume_leaders: LiveTick[];
  indices: LiveTick[];
  categories: { [key: string]: LiveTick[] };
  total_symbols: number;
}

export interface CategoryInfo {
  [category: string]: { symbol: string; available: boolean }[];
}

export interface MarketSnapshot {
  market_phase: string;
  market_message: string;
  is_market_open: boolean;
  next_event: string;
  next_event_time: string;
  seconds_to_next: number;
  data: LiveTick[];
}

export interface PriceTick {
  timestamp: string;
  price: number;
  volume: number;
}
