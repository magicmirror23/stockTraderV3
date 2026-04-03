/** Shared UI component interfaces */

export type TrendDirection = 'up' | 'down' | 'flat';

export interface StatCardConfig {
  label: string;
  value: string | number;
  delta?: string | number;
  deltaSuffix?: string;
  icon?: string;            // bootstrap-icons name without 'bi-' prefix
  trend?: TrendDirection;
  muted?: boolean;          // dim the card when data is stale
}

export type BadgeVariant =
  | 'buy' | 'sell' | 'hold'
  | 'long' | 'short'
  | 'open' | 'closed' | 'pending' | 'cancelled' | 'rejected' | 'filled'
  | 'running' | 'stopped' | 'error'
  | 'pre-open' | 'post-close'
  | 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export type SkeletonShape = 'card' | 'row' | 'table' | 'chart' | 'text' | 'circle';

export interface EmptyStateAction {
  label: string;
  icon?: string;
  variant?: string;         // Bootstrap btn variant: 'primary', 'outline-secondary', etc.
}
