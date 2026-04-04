import {
  Component,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  OnInit,
  OnDestroy,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { Subject, Subscription, takeUntil, timer, catchError, of } from 'rxjs';

import { PriceStreamService } from '../services/price-stream.service';
import { LiveStreamService } from '../services/live-stream.service';
import { MarketApiService } from '../services/market-api.service';
import { MarketStatus, LiveTick, PriceTick } from '../core/models/market.model';
import { Timeframe, OhlcSummary, WatchlistEntry } from '../core/models';
import { environment } from '../../environments/environment';

import {
  TradingChartComponent,
  PriceDisplayComponent,
  StateBadgeComponent,
  LoadingSkeletonComponent,
  EmptyStateComponent,
  OrderFormComponent,
  SymbolSearchComponent,
  ChartMode,
  OhlcBar,
  PricePoint,
  VolumeBar,
  BadgeVariant,
  OrderFormPayload,
  OrderFormConfig,
  SymbolResult,
} from '../shared';

@Component({
  selector: 'app-live-chart',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    TradingChartComponent,
    PriceDisplayComponent,
    StateBadgeComponent,
    LoadingSkeletonComponent,
    EmptyStateComponent,
    OrderFormComponent,
    SymbolSearchComponent,
  ],
  templateUrl: './live-chart.component.html',
  styleUrl: './live-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LiveChartComponent implements OnInit, OnDestroy {
  @ViewChild('symbolSearch') symbolSearchRef!: SymbolSearchComponent;
  @ViewChild('tradingChart') tradingChartRef!: TradingChartComponent;

  // ── Core State ──
  symbol = 'RELIANCE';
  chartMode: ChartMode = 'line';
  activeTimeframe: Timeframe = '1m';
  timeframes: Timeframe[] = ['1m', '5m', '15m', '1h', '1D'];

  // ── Instrument Data ──
  lastPrice = 0;
  priceChange = 0;
  priceChangePct = 0;
  prevClose = 0;
  dayVolume = 0;

  // ── OHLC Summary ──
  ohlc: OhlcSummary = { open: 0, high: 0, low: 0, close: 0, volume: 0, prevClose: 0 };

  // ── Chart Data ──
  lineData: PricePoint[] = [];
  ohlcData: OhlcBar[] = [];
  volumeData: VolumeBar[] = [];

  // ── Market ──
  market: MarketStatus | null = null;
  feedMode = 'replay';

  // ── Stream State ──
  streaming = false;
  connectingLive = false;
  loading = true;
  error = '';
  tickCount = 0;

  // ── Side Panels ──
  sidePanelCollapsed = false;
  orderConfig: OrderFormConfig = {};
  watchlist: WatchlistEntry[] = [];

  // ── Crosshair ──
  crosshairPrice: number | null = null;
  crosshairTime: string = '';

  private destroy$ = new Subject<void>();
  private streamSub: Subscription | null = null;

  constructor(
    private cdr: ChangeDetectorRef,
    private route: ActivatedRoute,
    private router: Router,
    private http: HttpClient,
    private priceStream: PriceStreamService,
    private liveStream: LiveStreamService,
    private marketApi: MarketApiService,
  ) {}

  // ── Lifecycle ──

  ngOnInit(): void {
    this.loadMarketStatus();
    this.loadFeedStatus();
    this.loadWatchlist();

    timer(30_000, 30_000).pipe(takeUntil(this.destroy$))
      .subscribe(() => this.loadMarketStatus());

    const urlSymbol = this.route.snapshot.paramMap.get('symbol');
    if (urlSymbol) {
      this.symbol = urlSymbol.toUpperCase();
    }

    this.loadSymbol(this.symbol);
  }

  ngOnDestroy(): void {
    this.stopStream();
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ── Computed ──

  get isMarketOpen(): boolean {
    return this.market?.phase === 'open' || this.market?.phase === 'pre_open';
  }

  get sessionBadge(): BadgeVariant {
    if (!this.market) return 'neutral';
    switch (this.market.phase) {
      case 'open': return 'success';
      case 'pre_open': return 'warning';
      default: return 'danger';
    }
  }

  get sessionLabel(): string {
    if (!this.market) return 'Loading…';
    switch (this.market.phase) {
      case 'open': return 'MARKET OPEN';
      case 'pre_open': return 'PRE-OPEN';
      case 'post_close': return 'POST CLOSE';
      case 'holiday': return 'HOLIDAY';
      case 'weekend': return 'WEEKEND';
      default: return 'CLOSED';
    }
  }

  get feedBadge(): BadgeVariant {
    return this.feedMode === 'live' ? 'success' : 'warning';
  }

  get feedLabel(): string {
    return this.feedMode === 'live' ? 'LIVE' : 'REPLAY';
  }

  get chartHeight(): number {
    return this.sidePanelCollapsed ? 580 : 520;
  }

  // ── Actions ──

  loadSymbol(symbol: string): void {
    this.symbol = symbol.toUpperCase().trim();
    if (!this.symbol) return;

    this.stopStream();
    this.resetChartData();
    this.loading = true;
    this.error = '';
    this.cdr.markForCheck();

    // Update browser URL
    this.router.navigate(['/chart', this.symbol], { replaceUrl: true });

    // Update order config
    this.orderConfig = {
      symbol: this.symbol,
      lastPrice: this.lastPrice || undefined,
    };

    // Load last close
    this.http.get<LiveTick>(`${environment.apiBaseUrl}/stream/last_close/${encodeURIComponent(this.symbol)}`).pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(tick => {
      if (tick && tick.price) {
        this.lastPrice = tick.price;
        this.prevClose = tick.prev_close ?? 0;
        this.priceChange = tick.change ?? 0;
        this.priceChangePct = tick.change_pct ?? 0;
        this.dayVolume = tick.volume ?? 0;
        this.ohlc = {
          open: tick.open ?? tick.price,
          high: tick.high ?? tick.price,
          low: tick.low ?? tick.price,
          close: tick.price,
          volume: tick.volume ?? 0,
          prevClose: tick.prev_close ?? 0,
        };
        this.orderConfig = { ...this.orderConfig, lastPrice: tick.price };
      }
      this.loading = false;
      this.cdr.markForCheck();

      // Auto-start streaming
      this.startStream();
    });
  }

  startStream(): void {
    this.stopStream();
    this.tickCount = 0;
    this.streaming = true;
    this.cdr.markForCheck();

    this.streamSub = this.priceStream.connect(this.symbol).subscribe({
      next: tick => {
        this.tickCount++;
        this.processTick(tick);
        this.cdr.markForCheck();
      },
      error: () => {
        this.streaming = false;
        this.error = 'Stream connection lost';
        this.cdr.markForCheck();
      },
    });
  }

  stopStream(): void {
    this.streamSub?.unsubscribe();
    this.streamSub = null;
    this.streaming = false;
  }

  connectLive(): void {
    this.connectingLive = true;
    this.cdr.markForCheck();

    this.liveStream.connectLive([this.symbol]).pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      if (res) {
        this.feedMode = res.feed_mode || (res.connected ? 'live' : 'replay');
      }
      this.connectingLive = false;
      this.cdr.markForCheck();
    });
  }

  setChartMode(mode: ChartMode): void {
    this.chartMode = mode;
    this.cdr.markForCheck();
  }

  setTimeframe(tf: Timeframe): void {
    this.activeTimeframe = tf;
    // Timeframe changes will be wired to historical data endpoint when available
    this.cdr.markForCheck();
  }

  toggleSidePanel(): void {
    this.sidePanelCollapsed = !this.sidePanelCollapsed;
    this.cdr.markForCheck();
  }

  onCrosshairMove(e: { time: any; price: number | null }): void {
    this.crosshairPrice = e.price;
    this.crosshairTime = e.time ? String(e.time) : '';
    this.cdr.markForCheck();
  }

  onSymbolSelect(result: SymbolResult): void {
    this.loadSymbol(result.symbol);
  }

  onOrderSubmit(payload: OrderFormPayload): void {
    // Order submission wired when trading API is integrated
    console.info('[ChartView] Order submitted:', payload);
  }

  navigateSymbol(sym: string): void {
    this.loadSymbol(sym);
  }

  trackBySymbol(_: number, item: WatchlistEntry): string {
    return item.symbol;
  }

  // ── Private ──

  private processTick(tick: PriceTick): void {
    if (!tick || !tick.timestamp || typeof tick.price !== 'number' || !Number.isFinite(tick.price)) {
      return;
    }

    const now = tick.timestamp;
    const price = tick.price;
    const vol = typeof tick.volume === 'number' && Number.isFinite(tick.volume) ? tick.volume : 0;

    // Update instrument header
    this.lastPrice = price;
    this.priceChange = this.prevClose ? price - this.prevClose : 0;
    this.priceChangePct = this.prevClose ? (this.priceChange / this.prevClose) * 100 : 0;

    // Update running OHLC
    if (this.ohlc.open === 0) this.ohlc.open = price;
    if (price > this.ohlc.high || this.ohlc.high === 0) this.ohlc.high = price;
    if (price < this.ohlc.low || this.ohlc.low === 0) this.ohlc.low = price;
    this.ohlc.close = price;
    this.ohlc.volume += vol;

    // Append to line data
    const point: PricePoint = { time: now, value: price };
    this.lineData = [...this.lineData, point];

    // Volume data
    const vBar: VolumeBar = {
      time: now,
      value: vol,
      color: price >= (this.lineData.length > 1 ? this.lineData[this.lineData.length - 2].value : price)
        ? '#2e7d3233'
        : '#d32f2f33',
    };
    this.volumeData = [...this.volumeData, vBar];

    // Keep max 600 points
    if (this.lineData.length > 600) {
      this.lineData = this.lineData.slice(-600);
      this.volumeData = this.volumeData.slice(-600);
    }
  }

  private resetChartData(): void {
    this.lineData = [];
    this.ohlcData = [];
    this.volumeData = [];
    this.ohlc = { open: 0, high: 0, low: 0, close: 0, volume: 0, prevClose: 0 };
    this.lastPrice = 0;
    this.priceChange = 0;
    this.priceChangePct = 0;
    this.prevClose = 0;
    this.dayVolume = 0;
    this.tickCount = 0;
    this.crosshairPrice = null;
    this.crosshairTime = '';
  }

  private loadMarketStatus(): void {
    this.marketApi.getMarketStatus().pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(m => {
      if (m) this.market = m;
      this.cdr.markForCheck();
    });
  }

  private loadFeedStatus(): void {
    this.liveStream.getFeedStatus().pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      if (s) this.feedMode = s.feed_mode || 'replay';
      this.cdr.markForCheck();
    });
  }

  private loadWatchlist(): void {
    this.liveStream.getWatchlistSnapshot().pipe(
      catchError(() => of({ data: [] })),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.watchlist = (res.data || []).slice(0, 10).map(t => ({
        symbol: t.symbol,
        price: t.price,
        change: t.change ?? 0,
        changePct: t.change_pct ?? 0,
      }));
      this.cdr.markForCheck();
    });
  }
}
