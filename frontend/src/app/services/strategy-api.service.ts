// Strategy intelligence & regime detection API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { RegimeResult, StrategyDecision } from '../core/models';

export { RegimeResult, StrategyDecision };

@Injectable({ providedIn: 'root' })
export class StrategyApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  detectRegime(symbol: string): Observable<RegimeResult> {
    return this.http.get<RegimeResult>(`${this.base}/regime/${symbol}`);
  }

  regimeHeatmap(symbols?: string[]): Observable<Record<string, any>> {
    const params: Record<string, string> = {};
    if (symbols?.length) {
      params['symbols'] = symbols.join(',');
    }
    return this.http.get<Record<string, any>>(`${this.base}/regime`, { params });
  }

  selectStrategy(payload: any): Observable<StrategyDecision> {
    return this.http.post<StrategyDecision>(`${this.base}/strategy/select`, payload);
  }

  getRecentDecisions(limit = 20): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/strategy/decisions`, { params: { limit } });
  }

  getStats(): Observable<any> {
    return this.http.get(`${this.base}/strategy/stats`);
  }
}
