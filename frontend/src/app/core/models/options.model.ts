/** Options strategy models */

export interface OptionLeg {
  instrument: string;
  option_type: string;
  strike: number;
  expiry: string;
  side: string;
  quantity: number;
  premium: number;
}

export interface StrategyRecommendation {
  strategy_type: string;
  legs: OptionLeg[];
  max_profit: number;
  max_loss: number;
  breakeven: number[];
  margin_required: number;
  rationale: string;
}
