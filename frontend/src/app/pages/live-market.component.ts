// Live market page component
import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { Subscription } from 'rxjs';
import { LiveStreamService, LiveTick, WatchlistItem, MarketOverview, CategoryInfo, MarketSnapshot } from '../services/live-stream.service';
import { MarketApiService, MarketStatus } from '../services/market-api.service';
import { TickerTapeComponent } from '../components/ticker-tape.component';
import { SparklineComponent } from '../components/sparkline.component';
import { LivePriceChartComponent, PriceTick } from '../components/live-price-chart.component';

@Component({
  selector: 'app-live-market',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TickerTapeComponent, SparklineComponent, LivePriceChartComponent],
  templateUrl: './live-market.component.html',
  styleUrl: './live-market.component.scss'
})
export class LiveMarketComponent implements OnInit, OnDestroy {
  symbolInput = 'RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK';
  placeholderSymbols = 'RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK';
  connected = false;
  tickCount = 0;
  feedMode = 'replay';
  connectingLive = false;
  market: MarketStatus | null = null;
  selectedSymbol = '';
  selectedChartData: PriceTick[] = [];
  selectedTick: LiveTick | null = null;
  overview: MarketOverview | null = null;
  tradeFeed: LiveTick[] = [];
  watchlistArray: WatchlistItem[] = [];

  // Indices & Category data
  indicesData: LiveTick[] = [];
  categoryNames: string[] = [];
  categorySymbolCounts: { [key: string]: number } = {};
  activeCategory = 'All';
  totalSymbols = 0;
  private allCategorySymbols: { [key: string]: string[] } = {};
  private allSymbolsList: string[] = [];

  // Add symbol
  newSymbolInput = '';
  addingSymbol = false;
  addSymbolMsg = '';
  addSymbolError = false;

  private subs: Subscription[] = [];
  private marketTimer: any;
  private overviewTimer: any;
  private chartDataMap = new Map<string, PriceTick[]>();

  constructor(
    private liveStream: LiveStreamService,
    private marketApi: MarketApiService,
  ) {}

  ngOnInit(): void {
    this.loadMarket();
    this.loadOverview();
    this.loadCategories();
    this.loadFeedStatus();
    this.marketTimer = setInterval(() => this.loadMarket(), 30_000);
    this.overviewTimer = setInterval(() => this.loadOverview(), 15_000);

    this.subs.push(
      this.liveStream.connected$.subscribe(c => this.connected = c),
      this.liveStream.watchlist$.subscribe(map => {
        this.watchlistArray = Array.from(map.values());
      }),
      this.liveStream.tick$.subscribe(tick => {
        this.tickCount++;
        // Track feed mode from incoming ticks
        if (tick.feed_mode) this.feedMode = tick.feed_mode;
        // Update trade feed (newest first, max 50)
        this.tradeFeed = [tick, ...this.tradeFeed.slice(0, 49)];
        // Update per-symbol chart data
        const arr = this.chartDataMap.get(tick.symbol) || [];
        arr.push({ timestamp: tick.timestamp, price: tick.price, volume: tick.volume });
        if (arr.length > 500) arr.shift();
        this.chartDataMap.set(tick.symbol, arr);
        // Update selected chart
        if (tick.symbol === this.selectedSymbol) {
          this.selectedChartData = [...arr];
          this.selectedTick = tick;
        }
        // Periodically refresh overview from live data
        if (this.tickCount % 20 === 0) {
          this.refreshOverviewFromLive();
        }
      }),
    );

    // Auto-load market snapshot (shows last close when market is closed)
    this.loadMarketSnapshot();

    // Auto-start WebSocket streaming after a short delay to let snapshot load first
    setTimeout(() => {
      if (!this.connected) {
        this.startStream();
      }
    }, 1500);
  }

  /** Load market snapshot - when market is closed, shows last close prices automatically */
  loadMarketSnapshot(): void {
    this.liveStream.getMarketSnapshot().subscribe({
      next: (snap: MarketSnapshot) => {
        if (!snap.is_market_open && snap.data && snap.data.length > 0) {
          // Market is closed - auto-populate with last close data
          const map = new Map<string, WatchlistItem>();
          for (const item of snap.data) {
            map.set(item.symbol, { ...item, sparkline: [item.price] });
          }
          this.liveStream.watchlist$.next(map);
          if (!this.selectedSymbol && snap.data.length > 0) {
            this.selectSymbol(snap.data[0].symbol);
          }
          // Build overview from snapshot
          const sorted = [...snap.data].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
          const indices = snap.data.filter((s: any) => ['NIFTY50', 'BANKNIFTY', 'SENSEX'].includes(s.symbol));
          if (indices.length > 0) this.indicesData = indices as any;
          this.overview = {
            gainers: sorted.filter(s => (s.change_pct ?? 0) > 0).slice(0, 10),
            losers: sorted.filter(s => (s.change_pct ?? 0) < 0).reverse().slice(0, 10),
            volume_leaders: [...snap.data].sort((a, b) => b.volume - a.volume).slice(0, 10),
            total_symbols: snap.data.length,
            indices: indices as any,
            categories: {},
          };
        } else {
          // Market is open or no snapshot data - load regular snapshot
          this.loadSnapshot();
        }
      },
      error: () => {
        // Fallback to regular snapshot on error
        this.loadSnapshot();
      }
    });
  }

  loadMarket(): void {
    this.marketApi.getMarketStatus().subscribe({
      next: m => this.market = m,
      error: () => {}
    });
  }

  loadOverview(): void {
    this.liveStream.getMarketOverview().subscribe({
      next: o => {
        this.overview = o;
        if (o.indices && o.indices.length > 0) {
          this.indicesData = o.indices;
        }
      },
      error: () => {}
    });
  }

  refreshOverviewFromLive(): void {
    const items = this.watchlistArray;
    if (items.length === 0) return;
    const sorted = [...items].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
    const indices = items.filter(i => ['NIFTY50', 'BANKNIFTY', 'SENSEX'].includes(i.symbol));
    if (indices.length > 0) this.indicesData = indices as any;
    this.overview = {
      gainers: sorted.filter(s => (s.change_pct ?? 0) > 0).slice(0, 10),
      losers: sorted.filter(s => (s.change_pct ?? 0) < 0).reverse().slice(0, 10),
      volume_leaders: [...items].sort((a, b) => b.volume - a.volume).slice(0, 10),
      total_symbols: items.length,
      indices: indices as any,
      categories: {},
    };
  }

  startStream(): void {
    const symbols = this.symbolInput.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    if (symbols.length === 0) return;
    this.tickCount = 0;
    this.tradeFeed = [];
    this.chartDataMap.clear();
    this.liveStream.connectMulti(symbols);
    if (!this.selectedSymbol && symbols.length > 0) {
      this.selectedSymbol = symbols[0];
    }
  }

  stopStream(): void {
    this.liveStream.disconnect();
  }

  loadSnapshot(): void {
    const symbols = this.symbolInput.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    this.liveStream.getWatchlistSnapshot(symbols.length ? symbols : undefined).subscribe({
      next: res => {
        const map = new Map<string, WatchlistItem>();
        for (const item of res.data) {
          map.set(item.symbol, { ...item, sparkline: [item.price] });
        }
        this.liveStream.watchlist$.next(map);
        if (!this.selectedSymbol && res.data.length > 0) {
          this.selectSymbol(res.data[0].symbol);
        }
        // Build overview from snapshot
        if (res.data.length > 0) {
          const sorted = [...res.data].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
          const indices = res.data.filter((s: any) => ['NIFTY50', 'BANKNIFTY', 'SENSEX'].includes(s.symbol));
          if (indices.length > 0) this.indicesData = indices as any;
          this.overview = {
            gainers: sorted.filter(s => (s.change_pct ?? 0) > 0).slice(0, 10),
            losers: sorted.filter(s => (s.change_pct ?? 0) < 0).reverse().slice(0, 10),
            volume_leaders: [...res.data].sort((a, b) => b.volume - a.volume).slice(0, 10),
            total_symbols: res.data.length,
            indices: indices as any,
            categories: {},
          };
        }
      },
      error: () => {}
    });
  }

  selectSymbol(symbol: string): void {
    this.selectedSymbol = symbol;
    this.selectedChartData = this.chartDataMap.get(symbol) || [];
    const wl = this.liveStream.watchlist$.value.get(symbol);
    this.selectedTick = wl || null;
  }

  loadCategories(): void {
    this.liveStream.getCategories().subscribe({
      next: (cats: CategoryInfo) => {
        this.categoryNames = Object.keys(cats);
        this.allCategorySymbols = {};
        this.allSymbolsList = [];
        let total = 0;
        for (const catName of this.categoryNames) {
          const syms = cats[catName].map((s: { symbol: string }) => s.symbol);
          this.allCategorySymbols[catName] = syms;
          this.categorySymbolCounts[catName] = syms.length;
          total += syms.length;
          this.allSymbolsList.push(...syms);
        }
        // Deduplicate
        this.allSymbolsList = [...new Set(this.allSymbolsList)];
        this.totalSymbols = this.allSymbolsList.length;
      },
      error: () => {}
    });
  }

  filterCategory(cat: string): void {
    this.activeCategory = cat;
    if (cat === 'All') {
      this.symbolInput = this.allSymbolsList.slice(0, 20).join(',');
    } else {
      const syms = this.allCategorySymbols[cat] || [];
      this.symbolInput = syms.join(',');
    }
  }

  streamAllSymbols(): void {
    this.symbolInput = this.allSymbolsList.join(',');
    this.startStream();
  }

  addNewSymbol(): void {
    const sym = this.newSymbolInput.trim().toUpperCase();
    if (!sym) return;

    // If already in the symbol list, just add to input
    if (this.allSymbolsList.includes(sym)) {
      this.addSymbolMsg = `${sym} is already available.`;
      this.addSymbolError = false;
      this.appendToSymbolInput(sym);
      this.newSymbolInput = '';
      return;
    }

    this.addingSymbol = true;
    this.addSymbolMsg = '';
    this.addSymbolError = false;

    this.liveStream.addSymbol(sym).subscribe({
      next: res => {
        this.addingSymbol = false;
        this.addSymbolMsg = res.message;
        this.addSymbolError = false;
        this.newSymbolInput = '';
        // Append to current symbol input and refresh categories
        this.appendToSymbolInput(sym);
        this.loadCategories();
      },
      error: (err) => {
        this.addingSymbol = false;
        this.addSymbolMsg = err.error?.detail || `Could not add ${sym}. Check the symbol name.`;
        this.addSymbolError = true;
      }
    });
  }

  private appendToSymbolInput(sym: string): void {
    const current = this.symbolInput.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    if (!current.includes(sym)) {
      current.push(sym);
      this.symbolInput = current.join(',');
    }
  }

  indexDisplayName(symbol: string): string {
    const map: { [k: string]: string } = {
      'NIFTY50': 'NIFTY 50',
      'BANKNIFTY': 'BANK NIFTY',
      'SENSEX': 'SENSEX',
    };
    return map[symbol] || symbol;
  }

  // -- Live Feed Controls ----------------------------------------------

  loadFeedStatus(): void {
    this.liveStream.getFeedStatus().subscribe({
      next: s => this.feedMode = s.feed_mode || 'replay',
      error: () => {}
    });
  }

  connectLiveFeed(): void {
    this.connectingLive = true;
    const symbols = this.symbolInput.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    this.liveStream.connectLive(symbols.length ? symbols : undefined).subscribe({
      next: res => {
        this.feedMode = res.feed_mode || (res.connected ? 'live' : 'replay');
        this.connectingLive = false;
      },
      error: () => { this.connectingLive = false; }
    });
  }

  disconnectLiveFeed(): void {
    this.liveStream.disconnectLive().subscribe({
      next: res => { this.feedMode = res['feed_mode'] || 'replay'; },
      error: () => {}
    });
  }

  ngOnDestroy(): void {
    this.liveStream.disconnect();
    this.subs.forEach(s => s.unsubscribe());
    clearInterval(this.marketTimer);
    clearInterval(this.overviewTimer);
  }

  trackBySymbol(_: number, item: { symbol: string }): string { return item.symbol; }
  trackByIdentity(_: number, item: string): string { return item; }
}

