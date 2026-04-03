/** System admin / MLOps models */

export interface ModelStatus {
  model_version: string;
  status: string;
  last_trained: string | null;
  accuracy: number | null;
}

export interface ModelReloadResponse {
  message: string;
  new_version: string;
  status: string;
}

export interface ModelVersion {
  version: string;
  created_at: string;
  accuracy?: number;
  status?: string;
}

export interface DriftResult {
  model_version: string;
  prediction_drift_psi: number | null;
  feature_drift_detected: boolean;
  avg_latency_ms: number | null;
  p99_latency_ms: number | null;
  error_rate: number | null;
  status: string;
}

export interface CanaryStatus {
  enabled: boolean;
  canary_version: string | null;
  stable_version: string | null;
  canary_traffic_pct: number;
  canary_accuracy: number | null;
  stable_accuracy: number | null;
}
