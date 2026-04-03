// Trade API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { TradeIntentRequest, TradeIntent, Execution } from '../core/models';

export { TradeIntentRequest, TradeIntent, Execution };

@Injectable({ providedIn: 'root' })
export class TradeApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  createIntent(request: TradeIntentRequest): Observable<TradeIntent> {
    return this.http.post<TradeIntent>(`${this.base}/trade_intent`, request);
  }

  execute(intentId: string): Observable<Execution> {
    return this.http.post<Execution>(`${this.base}/execute`, { intent_id: intentId });
  }
}

