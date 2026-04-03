/** Risk management models */

export interface RiskStatus {
  capital: number;
  used_capital: number;
  daily_pnl: number;
  daily_loss_pct: number;
  open_positions: number;
  circuit_breaker_active: boolean;
  daily_loss_lockout: boolean;
}

export interface RiskApproval {
  approved: boolean;
  reasons: string[];
  adjusted_quantity: number;
  risk_score: number;
}
