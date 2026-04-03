// Portfolio intelligence API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { PortfolioMetrics } from '../core/models';

export { PortfolioMetrics };

@Injectable({ providedIn: 'root' })
export class PortfolioApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  computeMetrics(payload: any): Observable<PortfolioMetrics> {
    return this.http.post<PortfolioMetrics>(`${this.base}/portfolio/metrics`, payload);
  }

  getExposureHeatmap(positions: Record<string, any>): Observable<Record<string, any>> {
    return this.http.post<Record<string, any>>(`${this.base}/portfolio/exposure`, { positions });
  }

  getCapitalAllocation(payload: any): Observable<any> {
    return this.http.post(`${this.base}/portfolio/allocation`, payload);
  }

  getDailySummary(payload: any): Observable<any> {
    return this.http.post(`${this.base}/portfolio/daily-summary`, payload);
  }
}
