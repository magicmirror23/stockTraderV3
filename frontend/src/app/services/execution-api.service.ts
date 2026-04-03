// Execution quality API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class ExecutionApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  getStats(): Observable<any> {
    return this.http.get(`${this.base}/execution/stats`);
  }

  getRecentReports(limit = 20): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/execution/reports`, { params: { limit } });
  }

  decideOrderType(payload: any): Observable<{ order_type: string }> {
    return this.http.post<{ order_type: string }>(`${this.base}/execution/decide-order-type`, payload);
  }

  priceCheck(payload: any): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(`${this.base}/execution/price-check`, payload);
  }

  liquidityCheck(payload: any): Observable<{ ok: boolean; warnings: string[] }> {
    return this.http.post<{ ok: boolean; warnings: string[] }>(`${this.base}/execution/liquidity-check`, payload);
  }
}
