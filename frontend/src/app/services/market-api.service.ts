// Market API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { MarketStatus, AccountProfile } from '../core/models';
import { BotStatus } from '../core/models';

export { MarketStatus, AccountProfile, BotStatus };

@Injectable({ providedIn: 'root' })
export class MarketApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  getMarketStatus(): Observable<MarketStatus> {
    return this.http.get<MarketStatus>(`${this.base}/market/status`);
  }

  getAccountProfile(): Observable<AccountProfile> {
    return this.http.get<AccountProfile>(`${this.base}/account/profile`);
  }

  getBotStatus(): Observable<BotStatus> {
    return this.http.get<BotStatus>(`${this.base}/bot/status`);
  }

  startBot(config?: any): Observable<any> {
    return this.http.post(`${this.base}/bot/start`, config || {});
  }

  stopBot(): Observable<any> {
    return this.http.post(`${this.base}/bot/stop`, {});
  }

  updateBotConfig(config: any): Observable<any> {
    return this.http.put(`${this.base}/bot/config`, config);
  }

  botConsent(resume: boolean): Observable<any> {
    return this.http.post(`${this.base}/bot/consent`, { resume });
  }
}