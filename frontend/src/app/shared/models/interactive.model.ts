/** Shared interactive component interfaces */

// ── Symbol Search ──────────────────────────────────────────

export interface SymbolResult {
  symbol: string;
  name: string;
  exchange?: string;
  type?: 'EQ' | 'FUT' | 'OPT' | 'IDX' | 'ETF';
  sector?: string;
}

// ── Order Form ─────────────────────────────────────────────

export type OrderSide = 'buy' | 'sell';
export type OrderType = 'market' | 'limit' | 'stop' | 'stop-limit';
export type ProductType = 'CNC' | 'MIS' | 'NRML';

export interface OrderFormPayload {
  symbol: string;
  side: OrderSide;
  orderType: OrderType;
  quantity: number;
  price: number | null;          // null for market orders
  triggerPrice: number | null;   // null unless stop/stop-limit
  productType: ProductType;
}

export interface OrderFormConfig {
  symbol?: string;
  side?: OrderSide;
  maxQuantity?: number;
  lotSize?: number;              // step size for quantity
  tickSize?: number;             // step size for price
  lastPrice?: number;            // pre-fill reference price
  allowedOrderTypes?: OrderType[];
  allowedProductTypes?: ProductType[];
  disabled?: boolean;
}

// ── Confirm Dialog ─────────────────────────────────────────

export type ConfirmSeverity = 'info' | 'warning' | 'danger';

export interface ConfirmDialogConfig {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  severity?: ConfirmSeverity;
  confirmIcon?: string;          // bootstrap-icons name
}

// ── Shortcut Key ───────────────────────────────────────────

export interface ShortcutDef {
  key: string;                   // e.g. 'b', 'Escape', 'Enter'
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  meta?: boolean;
}
