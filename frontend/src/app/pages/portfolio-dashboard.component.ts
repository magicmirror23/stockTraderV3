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

import { PortfolioApiService } from '../services/portfolio-api.service';
import { PortfolioMetrics } from '../core/models/portfolio.model';
import { Position, Holding } from '../core/models/position.model';

import {
  StatCardComponent,
  PnlDisplayComponent,
  PriceDisplayComponent,
  StateBadgeComponent,
  TradingChartComponent,
  SparklineComponent,
  LoadingSkeletonComponent,
  EmptyStateComponent,
  TrendDirection,
  PricePoint,
} from '../shared';

// ── View Models ────────────────────────────────────────────

interface KvEntry { key: string; value: number; }
interface ExposureCategory { key: string; entries: KvEntry[]; }

@Component({
  selector: 'app-portfolio-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    StatCardComponent,
    PnlDisplayComponent,
    PriceDisplayComponent,
    StateBadgeComponent,
    TradingChartComponent,
    SparklineComponent,
    LoadingSkeletonComponent,
    EmptyStateComponent,
  ],
  templateUrl: './portfolio-dashboard.component.html',
  styleUrl: './portfolio-dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PortfolioDashboardComponent implements OnInit, OnDestroy {

  // ── State ──
  metrics: PortfolioMetrics | null = null;
  positions: Position[] = [];
  holdings: Holding[] = [];
  equityCurve: PricePoint[] = [];

  exposure: Record<string, any> | null = null;
  exposureCategories: ExposureCategory[] = [];
  allocation: any | null = null;
  allocationEntries: KvEntry[] = [];

  strategyAttrib: KvEntry[] = [];
  sectorAttrib: KvEntry[] = [];
  symbolAttrib: KvEntry[] = [];
  greeksEntries: KvEntry[] = [];

  // Loading
  loadingMetrics = true;
  loadingPositions = true;
  loadingExposure = true;
  loadingAllocation = true;
  lastRefresh = '';

  private destroy$ = new Subject<void>();

  constructor(
    private cdr: ChangeDetectorRef,
    private portfolioApi: PortfolioApiService,
  ) {}

  ngOnInit(): void {
    this.loadAll();

    // Auto-refresh every 30s
    timer(30_000, 30_000).pipe(
      takeUntil(this.destroy$),
    ).subscribe(() => this.loadAll());
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ── Computed ──

  get totalValue(): number {
    return this.metrics?.total_equity ?? 0;
  }

  get investedValue(): number {
    return this.totalValue - (this.metrics?.cash ?? 0);
  }

  get dayPnl(): number {
    return this.metrics?.unrealized_pnl ?? 0;
  }

  get totalPnl(): number {
    return this.metrics?.net_pnl ?? 0;
  }

  get cashBalance(): number {
    return this.metrics?.cash ?? 0;
  }

  get exposurePct(): number {
    return (this.metrics?.exposure_pct ?? 0) * 100;
  }

  trend(val: number): TrendDirection {
    if (val > 0) return 'up';
    if (val < 0) return 'down';
    return 'flat';
  }

  fmtCurrency(val: number): string {
    return '₹' + Math.abs(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  fmtPct(val: number): string {
    return (val * 100).toFixed(2) + '%';
  }

  fmtRatio(val: number | null): string {
    return val != null ? val.toFixed(2) : '—';
  }

  trackByKey(_: number, item: KvEntry): string { return item.key; }
  trackByTicker(_: number, item: Position | Holding): string { return item.ticker; }

  refresh(): void {
    this.loadAll();
  }

  // ── Data Loading ──

  private loadAll(): void {
    this.loadingMetrics = true;
    this.loadingPositions = true;
    this.loadingExposure = true;
    this.loadingAllocation = true;
    this.cdr.markForCheck();

    // Metrics
    this.portfolioApi.computeMetrics({
      equity_curve: [],
      trades: [],
      positions: {},
      cash: 100000,
      initial_capital: 100000,
    }).pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(m => {
      if (m) {
        this.metrics = m;
        this.processAttribution(m);
      }
      this.loadingMetrics = false;
      this.lastRefresh = new Date().toLocaleTimeString('en-IN');
      this.cdr.markForCheck();
    });

    // Daily summary (positions + holdings + equity curve)
    this.portfolioApi.getDailySummary({
      positions: {},
      cash: 100000,
    }).pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(data => {
      if (data) {
        this.positions = (data.positions ?? []) as Position[];
        this.holdings = (data.holdings ?? []) as Holding[];
        const curve = (data.equity_curve ?? []) as { date: string; equity: number }[];
        this.equityCurve = curve.map(p => ({
          time: p.date,
          value: p.equity,
        }));
      }
      this.loadingPositions = false;
      this.cdr.markForCheck();
    });

    // Exposure
    this.portfolioApi.getExposureHeatmap({}).pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(d => {
      if (d) {
        this.exposure = d;
        this.exposureCategories = Object.entries(d)
          .filter(([, val]) => val && typeof val === 'object')
          .map(([key, val]) => ({
            key,
            entries: Object.entries(val as Record<string, number>)
              .map(([k, v]) => ({ key: k, value: v as number }))
              .sort((a, b) => b.value - a.value),
          }));
      }
      this.loadingExposure = false;
      this.cdr.markForCheck();
    });

    // Allocation
    this.portfolioApi.getCapitalAllocation({
      total_capital: 100000,
      current_positions: {},
    }).pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(d => {
      if (d) {
        this.allocation = d;
        this.allocationEntries = Object.entries(d)
          .filter(([, v]) => typeof v === 'number')
          .map(([key, value]) => ({ key, value: value as number }));
      }
      this.loadingAllocation = false;
      this.cdr.markForCheck();
    });
  }

  private processAttribution(m: PortfolioMetrics): void {
    this.strategyAttrib = Object.entries(m.by_strategy || {})
      .map(([key, value]) => ({ key, value: value as number }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));

    this.sectorAttrib = Object.entries(m.by_sector || {})
      .map(([key, value]) => ({ key, value: value as number }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));

    this.symbolAttrib = Object.entries(m.by_symbol || {})
      .map(([key, value]) => ({ key, value: value as number }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
      .slice(0, 8);

    this.greeksEntries = [
      { key: 'Delta', value: m.portfolio_delta },
      { key: 'Gamma', value: m.portfolio_gamma },
      { key: 'Theta', value: m.portfolio_theta },
      { key: 'Vega', value: m.portfolio_vega },
    ].filter(g => g.value !== 0);
  }
}
