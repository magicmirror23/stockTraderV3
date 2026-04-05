// Market API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { catchError, map, retry } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { MarketStatus, AccountProfile, BotStatus, BotConfig } from '../core/models';

export { MarketStatus, AccountProfile, BotStatus };

@Injectable({ providedIn: 'root' })
export class MarketApiService {
  private readonly base = environment.apiBaseUrl;

  constructor(private http: HttpClient) {}

  getMarketStatus(): Observable<MarketStatus> {
    return this.http.get<Partial<MarketStatus>>(`${this.base}/market/status`).pipe(
      retry({ count: 2, delay: 1000 }),
      map((status) => ({
        phase: status.phase ?? 'closed',
        message: this.cleanText(status.message ?? ''),
        ist_now: this.cleanText(status.ist_now ?? ''),
        next_event: this.cleanText(status.next_event ?? ''),
        next_event_time: this.cleanText(status.next_event_time ?? ''),
        seconds_to_next: status.seconds_to_next ?? 0,
        is_trading_day: status.is_trading_day ?? false,
      })),
    );
  }

  getAccountProfile(): Observable<AccountProfile> {
    // Prefer trading-service verification (same env as bot execution).
    return this.http.get<AccountProfile>(`${this.base}/bot/account/profile`).pipe(
      // Backward-compatible fallback to market-data endpoint.
      catchError(() => this.http.get<AccountProfile>(`${this.base}/account/profile`)),
    );
  }

  getBotStatus(): Observable<BotStatus> {
    return this.http.get<BotStatus>(`${this.base}/bot/status`);
  }

  startBot(config?: Partial<BotConfig>): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${this.base}/bot/start`, config || {});
  }

  stopBot(): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${this.base}/bot/stop`, {});
  }

  updateBotConfig(config: Partial<BotConfig>): Observable<Record<string, unknown>> {
    return this.http.put<Record<string, unknown>>(`${this.base}/bot/config`, config);
  }

  botConsent(resume: boolean): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${this.base}/bot/consent`, { resume });
  }

  private cleanText(value: string): string {
    return value
      .replace(/â€“/g, '-')
      .replace(/â€”/g, '-')
      .replace(/â€˜|â€™/g, "'")
      .replace(/â€œ|â€�/g, '"')
      .replace(/Â/g, '')
      .trim();
  }
}
