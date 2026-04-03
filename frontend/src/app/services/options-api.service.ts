// Options strategy API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { OptionLeg, StrategyRecommendation } from '../core/models';

export { OptionLeg, StrategyRecommendation };

@Injectable({ providedIn: 'root' })
export class OptionsApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  recommendStrategy(payload: any): Observable<StrategyRecommendation> {
    return this.http.post<StrategyRecommendation>(`${this.base}/options/recommend`, payload);
  }

  buildCoveredCall(payload: any): Observable<StrategyRecommendation> {
    return this.http.post<StrategyRecommendation>(`${this.base}/options/covered-call`, payload);
  }

  buildBullCallSpread(payload: any): Observable<StrategyRecommendation> {
    return this.http.post<StrategyRecommendation>(`${this.base}/options/bull-call-spread`, payload);
  }

  buildIronCondor(payload: any): Observable<StrategyRecommendation> {
    return this.http.post<StrategyRecommendation>(`${this.base}/options/iron-condor`, payload);
  }

  buildStraddle(payload: any): Observable<StrategyRecommendation> {
    return this.http.post<StrategyRecommendation>(`${this.base}/options/straddle`, payload);
  }

  computePayoff(legs: any[], spotRange?: [number, number], points = 100): Observable<any[]> {
    return this.http.post<any[]>(`${this.base}/options/payoff`, {
      legs,
      spot_range: spotRange,
      points,
    });
  }
}
