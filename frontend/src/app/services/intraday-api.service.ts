import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import {
  IntradaySignal,
  IntradayModelStatus,
  IntradayOptionSignal,
  IntradayExecutionStats,
  OpenPosition,
  SupervisorStatus,
  IntradayTrainStatus,
} from '../core/models';

@Injectable({ providedIn: 'root' })
export class IntradayApiService {
  private readonly base = environment.apiBaseUrl;

  constructor(private http: HttpClient) {}

  // ── Features ────────────────────────────────────────────────────
  getFeatureSymbols(): Observable<{ symbols: string[] }> {
    return this.http.get<{ symbols: string[] }>(`${this.base}/intraday/features/symbols`);
  }

  computeFeatures(symbol: string, interval = '1m', bars = 100): Observable<{
    symbol: string; interval: string; features: Record<string, number>; bars_used: number;
  }> {
    return this.http.post<any>(`${this.base}/intraday/features/compute`, { symbol, interval, bars });
  }

  // ── Prediction ──────────────────────────────────────────────────
  getIntradaySignal(symbol: string, features: Record<string, number>): Observable<IntradaySignal> {
    return this.http.post<IntradaySignal>(`${this.base}/intraday/predict/signal`, { symbol, features });
  }

  getIntradayBatch(symbols: string[], interval = '1m'): Observable<{ signals: IntradaySignal[]; timestamp: string }> {
    return this.http.post<any>(`${this.base}/intraday/predict/batch`, { symbols, interval });
  }

  getIntradayModelStatus(): Observable<IntradayModelStatus> {
    return this.http.get<IntradayModelStatus>(`${this.base}/intraday/predict/model/status`);
  }

  reloadIntradayModel(): Observable<{ status: string; version: string }> {
    return this.http.post<any>(`${this.base}/intraday/predict/model/reload`, {});
  }

  // ── Options signals ─────────────────────────────────────────────
  getOptionSignal(req: {
    symbol: string; underlying_trend: string; trend_confidence: number;
    underlying_price: number; atm_iv?: number; put_call_ratio?: number; days_to_expiry?: number;
  }): Observable<IntradayOptionSignal> {
    return this.http.post<IntradayOptionSignal>(`${this.base}/intraday/options/signal`, req);
  }

  // ── Execution ───────────────────────────────────────────────────
  getExecutionStats(): Observable<IntradayExecutionStats> {
    return this.http.get<IntradayExecutionStats>(`${this.base}/intraday/execution/stats`);
  }

  getOpenPositions(): Observable<{ count: number; positions: OpenPosition[] }> {
    return this.http.get<any>(`${this.base}/intraday/execution/positions`);
  }

  forceCloseAll(prices: Record<string, number> = {}): Observable<{ closed_count: number; total_pnl: number }> {
    return this.http.post<any>(`${this.base}/intraday/execution/force-close`, { prices });
  }

  resetExecutionDaily(): Observable<{ status: string }> {
    return this.http.post<any>(`${this.base}/intraday/execution/reset-daily`, {});
  }

  // ── Trade supervisor ────────────────────────────────────────────
  getSupervisorStatus(): Observable<SupervisorStatus> {
    return this.http.get<SupervisorStatus>(`${this.base}/intraday/supervisor/status`);
  }

  pauseTrading(): Observable<{ status: string; state: string }> {
    return this.http.post<any>(`${this.base}/intraday/supervisor/pause`, {});
  }

  resumeTrading(force = false): Observable<{ status: string; state: string }> {
    return this.http.post<any>(`${this.base}/intraday/supervisor/resume`, { force });
  }

  haltTrading(reason = 'manual'): Observable<{ status: string; state: string }> {
    return this.http.post<any>(`${this.base}/intraday/supervisor/halt?reason=${reason}`, {});
  }

  resetSupervisorDaily(equity = 100000): Observable<{ status: string }> {
    return this.http.post<any>(`${this.base}/intraday/supervisor/reset-daily?initial_equity=${equity}`, {});
  }

  // ── Training ────────────────────────────────────────────────────
  startIntradayTraining(config?: {
    target_type?: string; horizon_bars?: number; target_return_threshold?: number;
  }): Observable<{ status: string }> {
    return this.http.post<any>(`${this.base}/intraday/train/start`, config || {});
  }

  getIntradayTrainStatus(): Observable<IntradayTrainStatus> {
    return this.http.get<IntradayTrainStatus>(`${this.base}/intraday/train/status`);
  }
}
