// Risk management API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { RiskStatus, RiskApproval } from '../core/models';

export { RiskStatus, RiskApproval };

@Injectable({ providedIn: 'root' })
export class RiskApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  getStatus(): Observable<RiskStatus> {
    return this.http.get<RiskStatus>(`${this.base}/risk/status`);
  }

  getSectorExposure(): Observable<Record<string, number>> {
    return this.http.get<Record<string, number>>(`${this.base}/risk/exposure/sector`);
  }

  getInstrumentExposure(): Observable<Record<string, number>> {
    return this.http.get<Record<string, number>>(`${this.base}/risk/exposure/instrument`);
  }

  getStrategyExposure(): Observable<Record<string, number>> {
    return this.http.get<Record<string, number>>(`${this.base}/risk/exposure/strategy`);
  }

  getPortfolioGreeks(): Observable<Record<string, number>> {
    return this.http.get<Record<string, number>>(`${this.base}/risk/greeks`);
  }

  approveTrade(payload: any): Observable<RiskApproval> {
    return this.http.post<RiskApproval>(`${this.base}/risk/approve`, payload);
  }

  getSnapshots(limit = 20): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/risk/snapshot`, { params: { limit } });
  }
}
