// Live stream service — uses managed WebSocket via core/services/websocket.service
import { Injectable, OnDestroy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject, BehaviorSubject } from 'rxjs';
import { map, retry } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { LiveTick, FeedStatus, WatchlistItem, MarketOverview, CategoryInfo, MarketSnapshot } from '../core/models';
import { WebsocketService, ManagedConnection } from '../core/services/websocket.service';

export { LiveTick, FeedStatus, WatchlistItem, MarketOverview, CategoryInfo, MarketSnapshot };

@Injectable({ providedIn: 'root' })
export class LiveStreamService implements OnDestroy {
  private conn: ManagedConnection | null = null;
  private readonly base = environment.apiBaseUrl;

  /** Emits every incoming tick from multi-symbol stream */
  readonly tick$ = new Subject<LiveTick>();

  /** Current watchlist state (symbol → latest data + sparkline) */
  readonly watchlist$ = new BehaviorSubject<Map<string, WatchlistItem>>(new Map());

  /** Whether we are currently connected */
  readonly connected$ = new BehaviorSubject<boolean>(false);

  private sparklineMax = 30;

  constructor(private http: HttpClient, private wsService: WebsocketService) {}

  ngOnDestroy(): void {
    this.disconnect();
  }

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
    return this.http.get<MarketOverview>(`${this.base}/stream/market-overview`).pipe(
      retry({ count: 2, delay: 1000 }),
    );
  }

  /** Get symbol categories (Banking, IT, Pharma, Custom, etc.) */
  getCategories(): Observable<CategoryInfo> {
    return this.http.get<CategoryInfo>(`${this.base}/stream/categories`);
  }

  /** Add a new symbol — downloads data and makes it available */
  addSymbol(symbol: string): Observable<{ symbol: string; status: string; message: string }> {
    return this.http.post<{ symbol: string; status: string; message: string }>(
      `${this.base}/stream/add-symbol?symbol=${encodeURIComponent(symbol)}`, {}
    );
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
  disconnectLive(): Observable<Record<string, string>> {
    return this.http.post<Record<string, string>>(`${this.base}/stream/disconnect-live`, {});
  }

  /** Get market snapshot (last close prices when market is closed) */
  getMarketSnapshot(): Observable<MarketSnapshot> {
    return this.http.get<MarketSnapshot>(`${this.base}/stream/market-snapshot`).pipe(
      retry({ count: 2, delay: 1000 }),
      map((snapshot) => ({
        ...snapshot,
        market_message: this.cleanText(snapshot.market_message ?? ''),
        next_event: this.cleanText(snapshot.next_event ?? ''),
        next_event_time: this.cleanText(snapshot.next_event_time ?? ''),
      })),
    );
  }

  /** Connect multi-symbol stream via managed WebSocket (auto-reconnect + SSE fallback). */
  connectMulti(symbols: string[]): void {
    this.disconnect();

    this.conn = this.wsService.connect('/stream/multi');
    this.connected$.next(true);

    // Subscribe once the connection is up
    this.conn.state$.subscribe(state => {
      this.connected$.next(state === 'connected');
      if (state === 'connected') {
        this.conn!.send({ action: 'subscribe', symbols });
      }
    });

    this.conn.messages$.subscribe(msg => {
      const tick = msg as LiveTick;
      this.tick$.next(tick);
      this.updateWatchlist(tick);
    });
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
    this.conn?.disconnect();
    this.conn = null;
    this.connected$.next(false);
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
