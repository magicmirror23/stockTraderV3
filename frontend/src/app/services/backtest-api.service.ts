// Backtest API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { BacktestRunRequest, BacktestRunResponse, BacktestTrade, BacktestResults } from '../core/models';

export { BacktestRunRequest, BacktestRunResponse, BacktestTrade, BacktestResults };

@Injectable({ providedIn: 'root' })
export class BacktestApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  runBacktest(request: BacktestRunRequest): Observable<BacktestRunResponse> {
    return this.http.post<BacktestRunResponse>(`${this.base}/backtest/run`, request);
  }

  getResults(jobId: string): Observable<BacktestResults> {
    return this.http.get<BacktestResults>(`${this.base}/backtest/${encodeURIComponent(jobId)}/results`);
  }
}

