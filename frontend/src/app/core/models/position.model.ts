/** Position & holdings models */

export interface Position {
  ticker: string;
  side: 'long' | 'short';
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  option_type?: string;
  strike?: number;
  expiry?: string;
}

export interface Holding {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_value: number;
  total_return: number;
  total_return_pct: number;
  sector?: string;
}
