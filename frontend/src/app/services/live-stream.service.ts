// Live stream service
import { Injectable, NgZone } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject, BehaviorSubject } from 'rxjs';
import { LiveTick, FeedStatus, WatchlistItem, MarketOverview, CategoryInfo, MarketSnapshot } from '../core/models';

export { LiveTick, FeedStatus, WatchlistItem, MarketOverview, CategoryInfo, MarketSnapshot };

@Injectable({ providedIn: 'root' })
export class LiveStreamService {
  private ws: WebSocket | null = null;
  private sse: EventSource | null = null;
  private readonly base = '/api/v1';

  /** Emits every incoming tick from multi-symbol stream */
  readonly tick$ = new Subject<LiveTick>();

  /** Current watchlist state (symbol → latest data + sparkline) */
  readonly watchlist$ = new BehaviorSubject<Map<string, WatchlistItem>>(new Map());

  /** Whether we are currently connected */
  readonly connected$ = new BehaviorSubject<boolean>(false);

  private sparklineMax = 30;

  constructor(private ngZone: NgZone, private http: HttpClient) {}

  /** Fetch available symbols from backend */
  getSymbols(): Observable<{ symbols: string[] }> {
    return this.http.get<{ symbols: string[] }>(`${this.base}/stream/symbols`);
  }

  /** Get a one-time watchlist snapshot (no streaming) */
  getWatchlistSnapshot(symbols?: string[]): Observable<{ data: LiveTick[] }> {
    const q = symbols?.join(',') || '';
    return this.http.get<{ data: LiveTick[] }>(`${this.base}/stream/watchlist?symbols=${q}`);
  }

  /** Get market overview (gainers, losers, volume, indices) */
  getMarketOverview(): Observable<MarketOverview> {
    return this.http.get<MarketOverview>(`${this.base}/stream/market-overview`);
  }

  /** Get symbol categories (Banking, IT, Pharma, etc.) */
  getCategories(): Observable<CategoryInfo> {
    return this.http.get<CategoryInfo>(`${this.base}/stream/categories`);
  }

  /** Get current feed status (live vs replay) */
  getFeedStatus(): Observable<FeedStatus> {
    return this.http.get<FeedStatus>(`${this.base}/stream/feed-status`);
  }

  /** Connect to AngelOne live feed */
  connectLive(symbols?: string[]): Observable<FeedStatus> {
    const q = symbols?.join(',') || '';
    return this.http.post<FeedStatus>(`${this.base}/stream/connect-live?symbols=${q}`, {});
  }

  /** Disconnect from live feed (fall back to replay) */
  disconnectLive(): Observable<any> {
    return this.http.post(`${this.base}/stream/disconnect-live`, {});
  }

  /** Get market snapshot (last close prices when market is closed) */
  getMarketSnapshot(): Observable<MarketSnapshot> {
    return this.http.get<MarketSnapshot>(`${this.base}/stream/market-snapshot`);
  }

  /** Connect multi-symbol WebSocket stream. Falls back to SSE. */
  connectMulti(symbols: string[]): void {
    this.disconnect();

    const wsUrl = `ws://${window.location.host}${this.base}/stream/multi`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.connected$.next(true);
        this.ws!.send(JSON.stringify({ action: 'subscribe', symbols }));
      };

      this.ws.onmessage = (event) => {
        this.ngZone.run(() => {
          const tick: LiveTick = JSON.parse(event.data);
          this.tick$.next(tick);
          this.updateWatchlist(tick);
        });
      };

      this.ws.onerror = () => {
        this.ws?.close();
        this.connectSSE(symbols);
      };

      this.ws.onclose = () => {
        if (this.connected$.value) {
          this.connected$.next(false);
        }
      };
    } catch {
      this.connectSSE(symbols);
    }
  }

  /** SSE fallback for multi-symbol streaming */
  private connectSSE(symbols: string[]): void {
    const url = `${this.base}/stream/multi?symbols=${symbols.join(',')}`;
    this.sse = new EventSource(url);
    this.connected$.next(true);

    this.sse.onmessage = (event) => {
      this.ngZone.run(() => {
        const tick: LiveTick = JSON.parse(event.data);
        this.tick$.next(tick);
        this.updateWatchlist(tick);
      });
    };

    this.sse.onerror = () => {
      this.sse?.close();
      this.connected$.next(false);
    };
  }

  /** Update the watchlist BehaviorSubject with new tick data */
  private updateWatchlist(tick: LiveTick): void {
    const map = new Map(this.watchlist$.value);
    const existing = map.get(tick.symbol);
    const sparkline = existing?.sparkline || [];
    sparkline.push(tick.price);
    if (sparkline.length > this.sparklineMax) {
      sparkline.shift();
    }
    map.set(tick.symbol, { ...tick, sparkline });
    this.watchlist$.next(map);
  }

  /** Disconnect all streams */
  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    if (this.sse) {
      this.sse.close();
      this.sse = null;
    }
    this.connected$.next(false);
  }
}