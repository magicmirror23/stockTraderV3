import {
  Component,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  OnInit,
  OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { Subject, takeUntil, timer, switchMap, catchError, of, forkJoin } from 'rxjs';

// Services
import { MarketApiService } from '../services/market-api.service';
import { LiveStreamService } from '../services/live-stream.service';
import { StrategyApiService } from '../services/strategy-api.service';
import { IntelligenceApiService } from '../services/intelligence-api.service';

// Core models
import {
  MarketStatus,
  LiveTick,
  WatchlistItem,
  MarketOverview,
  MarketSnapshot,
  FeedStatus,
} from '../core/models/market.model';
import { RegimeResult } from '../core/models/prediction.model';

// Shared components
import {
  StatCardComponent,
  PriceDisplayComponent,
  SparklineComponent,
  StateBadgeComponent,
  LoadingSkeletonComponent,
  EmptyStateComponent,
  TickerTapeComponent,
  TickerTapeItem,
  BadgeVariant,
} from '../shared';

import {
  IndexCard,
  MoverRow,
  SectorPerf,
  RegimeCard,
  MarketBreadth,
} from '../core/models';

interface NewsItem {
  title: string;
  source: string;
  url: string;
  publishedAt: string;
  sentiment?: string;
}

// ── Index display-name map ──

const INDEX_NAMES: Record<string, string> = {
  'NIFTY 50':       'NIFTY 50',
  'NIFTY BANK':     'BANK NIFTY',
  'NIFTY IT':       'NIFTY IT',
  'NIFTY FIN SERVICE': 'FIN NIFTY',
  'INDIA VIX':      'INDIA VIX',
  'SENSEX':         'SENSEX',
  'NIFTY NEXT 50':  'NIFTY NEXT 50',
  'NIFTY MIDCAP 100': 'MIDCAP 100',
};

@Component({
  selector: 'app-market-overview',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    StatCardComponent,
    PriceDisplayComponent,
    SparklineComponent,
    StateBadgeComponent,
    LoadingSkeletonComponent,
    EmptyStateComponent,
    TickerTapeComponent,
  ],
  templateUrl: './market-overview.component.html',
  styleUrl: './market-overview.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MarketOverviewComponent implements OnInit, OnDestroy {

  // ── State ──
  marketStatus: MarketStatus | null = null;
  feedStatus: FeedStatus | null = null;
  indices: IndexCard[] = [];
  gainers: MoverRow[] = [];
  losers: MoverRow[] = [];
  volumeLeaders: MoverRow[] = [];
  sectors: SectorPerf[] = [];
  regimes: RegimeCard[] = [];
  watchlist: WatchlistItem[] = [];
  tickerItems: TickerTapeItem[] = [];
  news: NewsItem[] = [];
  breadth: MarketBreadth = { advances: 0, declines: 0, unchanged: 0, total: 0, advanceRatio: 0 };
  vix: IndexCard | null = null;

  // Loading states
  loadingMarket = true;
  loadingOverview = true;
  loadingRegime = true;
  loadingNews = true;
  loadError = false;
  wsConnected = false;
  totalSymbols = 0;
  lastRefresh = '';

  private destroy$ = new Subject<void>();

  // ── Regime symbols to track ──
  private readonly regimeSymbols = ['NIFTY 50', 'NIFTY BANK', 'RELIANCE', 'TCS', 'HDFCBANK', 'INFY'];

  constructor(
    private cdr: ChangeDetectorRef,
    private marketApi: MarketApiService,
    private liveStream: LiveStreamService,
    private strategyApi: StrategyApiService,
    private intelligenceApi: IntelligenceApiService,
  ) {}

  private liveTickCount = 0;

  ngOnInit(): void {
    this.loadAll();

    // Auto-start WebSocket stream for real-time price updates
    this.startLiveStream();

    // Poll market status every 30s
    timer(30_000, 30_000).pipe(
      switchMap(() => this.marketApi.getMarketStatus().pipe(catchError(() => of(null)))),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      if (s) { this.marketStatus = s; this.cdr.markForCheck(); }
    });

    // Poll overview data every 15s as backup
    timer(15_000, 15_000).pipe(
      switchMap(() => this.liveStream.getMarketOverview().pipe(catchError(() => of(null)))),
      takeUntil(this.destroy$),
    ).subscribe(ov => {
      if (ov) { this.processOverview(ov); this.cdr.markForCheck(); }
    });

    // Track WS connection
    this.liveStream.connected$.pipe(takeUntil(this.destroy$))
      .subscribe(c => { this.wsConnected = c; this.cdr.markForCheck(); });

    // Live tick updates for watchlist + overview rebuild
    this.liveStream.watchlist$.pipe(takeUntil(this.destroy$))
      .subscribe(map => {
        this.watchlist = Array.from(map.values()).slice(0, 10);
        this.updateTickerTape(map);
        // Rebuild overview panels from live data every few ticks
        if (map.size >= 5) {
          this.rebuildOverviewFromLive(map);
        }
        this.cdr.markForCheck();
      });

    // Count live ticks for overview rebuild throttling
    this.liveStream.tick$.pipe(takeUntil(this.destroy$))
      .subscribe(() => { this.liveTickCount++; });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  /** Start a multi-symbol WebSocket stream for real-time price updates. */
  private startLiveStream(): void {
    this.liveStream.getSymbols().pipe(
      catchError(() => of({ symbols: [] as string[] })),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      const symbols = res.symbols.length > 0 ? res.symbols : [
        'RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'SBIN',
        'AXISBANK', 'KOTAKBANK', 'WIPRO', 'HCLTECH', 'SUNPHARMA',
        'TATASTEEL', 'LT', 'ITC', 'HINDUNILVR', 'BAJFINANCE',
        'NIFTY50', 'BANKNIFTY', 'SENSEX',
      ];
      this.liveStream.connectMulti(symbols);
    });
  }

  /** Rebuild overview panels (gainers, losers, etc.) from live WebSocket data. */
  private rebuildOverviewFromLive(map: Map<string, WatchlistItem>): void {
    const items = Array.from(map.values());
    const indexSymbols = new Set(['NIFTY50', 'BANKNIFTY', 'SENSEX']);
    const indices = items.filter(i => indexSymbols.has(i.symbol));
    const stocks = items.filter(i => !indexSymbols.has(i.symbol));

    if (indices.length > 0) {
      this.indices = indices.map(t => this.toIndexCard(t as any));
      this.vix = this.indices.find(i => i.displayName === 'INDIA VIX') ?? null;
    }

    const sorted = [...stocks].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
    this.gainers = sorted.filter(s => (s.change_pct ?? 0) > 0).slice(0, 8).map(t => this.toMoverRow(t as any));
    this.losers = sorted.filter(s => (s.change_pct ?? 0) < 0).reverse().slice(0, 8).map(t => this.toMoverRow(t as any));
    this.volumeLeaders = [...stocks].sort((a, b) => b.volume - a.volume).slice(0, 6).map(t => this.toMoverRow(t as any));
    this.totalSymbols = items.length;

    // Breadth
    const adv = stocks.filter(t => (t.change_pct ?? 0) > 0).length;
    const dec = stocks.filter(t => (t.change_pct ?? 0) < 0).length;
    this.breadth = {
      advances: adv,
      declines: dec,
      unchanged: stocks.length - adv - dec,
      total: stocks.length,
      advanceRatio: stocks.length > 0 ? adv / stocks.length : 0,
    };
  }

  // ── Public helpers for template ──

  get sessionPhaseLabel(): string {
    if (!this.marketStatus) return 'Loading…';
    switch (this.marketStatus.phase) {
      case 'open':       return 'Market Open';
      case 'pre_open':   return 'Pre-Open Session';
      case 'post_close': return 'Post-Close';
      case 'closed':     return 'Market Closed';
      case 'holiday':    return 'Market Holiday';
      case 'weekend':    return 'Weekend';
      default:           return this.marketStatus.phase;
    }
  }

  get sessionPhaseBadge(): BadgeVariant {
    if (!this.marketStatus) return 'neutral';
    switch (this.marketStatus.phase) {
      case 'open':       return 'running';
      case 'pre_open':   return 'warning';
      default:           return 'neutral';
    }
  }

  get breadthAdvPct(): number {
    return this.breadth.total > 0 ? (this.breadth.advances / this.breadth.total) * 100 : 50;
  }

  get breadthDecPct(): number {
    return this.breadth.total > 0 ? (this.breadth.declines / this.breadth.total) * 100 : 50;
  }

  // Expose Math for template
  readonly Math = Math;

  regimeBadge(regime: string): BadgeVariant {
    switch (regime?.toLowerCase()) {
      case 'bullish': case 'uptrend':     return 'buy';
      case 'bearish': case 'downtrend':   return 'sell';
      case 'sideways': case 'mean_revert': return 'hold';
      case 'volatile': case 'high_vol':   return 'warning';
      default:                            return 'neutral';
    }
  }

  trackBySymbol(_: number, item: { symbol: string }): string {
    return item.symbol;
  }

  trackBySector(_: number, item: SectorPerf): string {
    return item.sector;
  }

  refresh(): void {
    this.loadAll();
  }

  // ── Data loading ──

  private loadAll(): void {
    this.loadingMarket = true;
    this.loadingOverview = true;
    this.loadingRegime = true;
    this.loadingNews = true;
    this.loadError = false;
    this.cdr.markForCheck();

    // Parallel: market status + feed status
    forkJoin({
      market: this.marketApi.getMarketStatus().pipe(catchError(() => of(null))),
      feed: this.liveStream.getFeedStatus().pipe(catchError(() => of(null))),
    }).pipe(takeUntil(this.destroy$)).subscribe(({ market, feed }) => {
      if (market) this.marketStatus = market;
      if (feed) this.feedStatus = feed;
      if (!market && !feed) this.loadError = true;
      this.loadingMarket = false;
      this.lastRefresh = new Date().toLocaleTimeString('en-IN');
      this.cdr.markForCheck();
    });

    // Market overview (gainers, losers, indices)
    this.liveStream.getMarketOverview().pipe(
      catchError(() => {
        // Fallback to snapshot when market closed
        return this.liveStream.getMarketSnapshot().pipe(
          catchError(() => of(null)),
        );
      }),
      takeUntil(this.destroy$),
    ).subscribe(data => {
      if (data && 'gainers' in data) {
        this.processOverview(data as MarketOverview);
      } else if (data && 'data' in data) {
        this.processSnapshot(data as MarketSnapshot);
      }
      this.loadingOverview = false;
      this.cdr.markForCheck();
    });

    // Regime heatmap
    this.strategyApi.regimeHeatmap(this.regimeSymbols).pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(data => {
      if (data) {
        this.regimes = Object.entries(data)
          .filter(([, v]) => v && typeof v === 'object' && 'regime' in (v as any))
          .map(([sym, v]) => ({
            symbol: sym,
            regime: (v as any).regime || 'unknown',
            confidence: (v as any).confidence || 0,
            volatility: (v as any).volatility || 0,
          }));
      }
      this.loadingRegime = false;
      this.cdr.markForCheck();
    });

    // News
    this.intelligenceApi.getRecentAlerts(8).pipe(
      catchError(() => of([])),
      takeUntil(this.destroy$),
    ).subscribe(alerts => {
      this.news = (alerts || []).map((a: any) => ({
        title: a.message || a.title || `${a.type} alert: ${a.ticker}`,
        source: a.type || 'System',
        url: '',
        publishedAt: a.timestamp || '',
        sentiment: a.severity || 'neutral',
      }));
      this.loadingNews = false;
      this.cdr.markForCheck();
    });
  }

  private processOverview(ov: MarketOverview): void {
    this.totalSymbols = ov.total_symbols;

    // Indices
    this.indices = (ov.indices || []).map(t => this.toIndexCard(t));
    this.vix = this.indices.find(i => i.displayName === 'INDIA VIX') ?? null;

    // Movers
    this.gainers = (ov.gainers || []).slice(0, 8).map(t => this.toMoverRow(t));
    this.losers = (ov.losers || []).slice(0, 8).map(t => this.toMoverRow(t));
    this.volumeLeaders = (ov.volume_leaders || []).slice(0, 6).map(t => this.toMoverRow(t));

    // Sectors from categories
    this.sectors = Object.entries(ov.categories || {}).map(([sector, ticks]) => {
      const avg = ticks.length > 0
        ? ticks.reduce((s, t) => s + (t.change_pct ?? 0), 0) / ticks.length
        : 0;
      return { sector, changePct: avg, symbolCount: ticks.length };
    }).sort((a, b) => b.changePct - a.changePct);

    // Breadth from all data
    const allTicks = [
      ...(ov.gainers || []),
      ...(ov.losers || []),
      ...(ov.volume_leaders || []),
    ];
    // Deduplicate by symbol
    const unique = new Map<string, LiveTick>();
    allTicks.forEach(t => unique.set(t.symbol, t));
    // Also count across categories
    Object.values(ov.categories || {}).forEach(arr =>
      arr.forEach(t => unique.set(t.symbol, t))
    );

    const all = Array.from(unique.values());
    const adv = all.filter(t => (t.change_pct ?? 0) > 0).length;
    const dec = all.filter(t => (t.change_pct ?? 0) < 0).length;
    const unch = all.length - adv - dec;
    this.breadth = {
      advances: adv,
      declines: dec,
      unchanged: unch,
      total: all.length,
      advanceRatio: all.length > 0 ? adv / all.length : 0,
    };

    // Ticker tape
    this.tickerItems = [...(ov.gainers || []), ...(ov.losers || [])].slice(0, 20).map(t => ({
      symbol: t.symbol,
      price: t.price,
      change: t.change ?? 0,
      changePct: t.change_pct ?? 0,
    }));
  }

  private processSnapshot(snap: MarketSnapshot): void {
    const ticks = snap.data || [];
    this.totalSymbols = ticks.length;

    // Split indices vs stocks
    const indexSymbols = new Set(Object.keys(INDEX_NAMES));
    const idxTicks = ticks.filter(t => indexSymbols.has(t.symbol));
    const stockTicks = ticks.filter(t => !indexSymbols.has(t.symbol));

    this.indices = idxTicks.map(t => this.toIndexCard(t));
    this.vix = this.indices.find(i => i.displayName === 'INDIA VIX') ?? null;

    // Sort for gainers/losers
    const sorted = [...stockTicks].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
    this.gainers = sorted.slice(0, 8).map(t => this.toMoverRow(t));
    this.losers = sorted.slice(-8).reverse().map(t => this.toMoverRow(t));
    this.volumeLeaders = [...stockTicks]
      .sort((a, b) => b.volume - a.volume)
      .slice(0, 6)
      .map(t => this.toMoverRow(t));

    // Breadth
    const adv = stockTicks.filter(t => (t.change_pct ?? 0) > 0).length;
    const dec = stockTicks.filter(t => (t.change_pct ?? 0) < 0).length;
    this.breadth = {
      advances: adv,
      declines: dec,
      unchanged: stockTicks.length - adv - dec,
      total: stockTicks.length,
      advanceRatio: stockTicks.length > 0 ? adv / stockTicks.length : 0,
    };

    this.tickerItems = sorted.slice(0, 20).map(t => ({
      symbol: t.symbol,
      price: t.price,
      change: t.change ?? 0,
      changePct: t.change_pct ?? 0,
    }));
  }

  private toIndexCard(t: LiveTick): IndexCard {
    return {
      symbol: t.symbol,
      displayName: INDEX_NAMES[t.symbol] || t.symbol,
      price: t.price,
      change: t.change ?? 0,
      changePct: t.change_pct ?? 0,
      sparkline: [],
    };
  }

  private toMoverRow(t: LiveTick): MoverRow {
    return {
      symbol: t.symbol,
      price: t.price,
      change: t.change ?? 0,
      changePct: t.change_pct ?? 0,
      volume: t.volume,
    };
  }

  private updateTickerTape(map: Map<string, WatchlistItem>): void {
    if (map.size === 0) return;
    this.tickerItems = Array.from(map.values()).slice(0, 20).map(w => ({
      symbol: w.symbol,
      price: w.price,
      change: w.change ?? 0,
      changePct: w.change_pct ?? 0,
    }));
  }
}
