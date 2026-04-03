/** Prediction & signal models */

export interface PredictionResult {
  ticker: string;
  action: 'buy' | 'sell' | 'hold';
  confidence: number;
  expected_return: number;
  model_version: string;
  calibration_score?: number;
  shap_top_features?: string[];
  timestamp: string;
}

export interface Greeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho?: number;
  iv?: number;
}

export interface OptionSignal {
  underlying: string;
  strike: number;
  expiry: string;
  option_type: 'CE' | 'PE';
  action: 'buy' | 'sell' | 'hold';
  confidence: number;
  expected_return: number;
  greeks: Greeks;
  iv_percentile?: number;
  model_version: string;
  calibration_score?: number;
  shap_top_features?: string[];
  timestamp: string;
}

export interface RegimeResult {
  symbol: string;
  regime: string;
  confidence: number;
  volatility: number;
  trend: number;
  indicators: Record<string, number>;
}

export interface StrategyDecision {
  ticker: string;
  strategy: string;
  reason: string;
  confidence: number;
  params: Record<string, any>;
}
