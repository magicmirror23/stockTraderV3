import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subject, takeUntil, timer, catchError, of, forkJoin } from 'rxjs';

import { RiskApiService } from '../services/risk-api.service';
import { RiskStatus } from '../core/models/risk.model';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  EmptyStateComponent, StatCardConfig, BadgeVariant,
} from '../shared';

@Component({
  selector: 'app-risk-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent, EmptyStateComponent,
  ],
  templateUrl: './risk-dashboard.component.html',
  styleUrl: './risk-dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskDashboardComponent implements OnInit, OnDestroy {
  // Data
  status: RiskStatus | null = null;
  sectorExposure: { key: string; value: number }[] = [];
  greeksEntries: { key: string; value: number }[] = [];
  snapshots: any[] = [];

  // State
  loading = true;
  loadError = false;

  private destroy$ = new Subject<void>();

  constructor(
    private cdr: ChangeDetectorRef,
    private riskApi: RiskApiService,
  ) {}

  ngOnInit(): void {
    this.loadAll();
    timer(15_000, 15_000).pipe(takeUntil(this.destroy$)).subscribe(() => this.loadAll());
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ── Computed ──
  get statusCards(): StatCardConfig[] {
    if (!this.status) return [];
    const capital = this.asNum(this.status.capital);
    const usedCapital = this.asNum(this.status.used_capital);
    const dailyPnl = this.asNum(this.status.daily_pnl);
    const openPositions = this.asNum(this.status.open_positions);
    return [
      { label: 'Capital', value: `₹${capital.toLocaleString('en-IN')}`, icon: 'bank' },
      { label: 'Used Capital', value: `₹${usedCapital.toLocaleString('en-IN')}`, icon: 'cash-coin' },
      {
        label: 'Daily P&L', value: `₹${dailyPnl.toLocaleString('en-IN')}`,
        icon: 'graph-up-arrow', trend: dailyPnl >= 0 ? 'up' : 'down',
      },
      { label: 'Open Positions', value: openPositions, icon: 'stack' },
    ];
  }

  get circuitBadge(): BadgeVariant {
    return this.status?.circuit_breaker_active ? 'danger' : 'success';
  }

  get lockoutBadge(): BadgeVariant {
    return this.status?.daily_loss_lockout ? 'danger' : 'success';
  }

  get capitalUsedPct(): number {
    if (!this.status) return 0;
    const capital = this.asNum(this.status.capital);
    const used = this.asNum(this.status.used_capital);
    if (!capital) return 0;
    return (used / capital) * 100;
  }

  barClass(pct: number): string {
    if (pct > 25) return 'rd__bar-fill--danger';
    if (pct > 15) return 'rd__bar-fill--warn';
    return 'rd__bar-fill--ok';
  }

  // ── Private ──
  loadAll(): void {
    this.loadError = false;
    forkJoin({
      status: this.riskApi.getStatus().pipe(catchError(() => of(null))),
      sector: this.riskApi.getSectorExposure().pipe(catchError(() => of({} as Record<string, number>))),
      greeks: this.riskApi.getPortfolioGreeks().pipe(catchError(() => of({} as Record<string, number>))),
      snapshots: this.riskApi.getSnapshots().pipe(catchError(() => of([] as any[]))),
    }).pipe(takeUntil(this.destroy$)).subscribe(({ status, sector, greeks, snapshots }) => {
      if (status) {
        this.status = status;
      } else {
        this.loadError = true;
      }
      this.sectorExposure = Object.entries(sector)
        .map(([key, value]) => ({ key, value: this.asNum(value) }))
        .sort((a, b) => b.value - a.value);
      this.greeksEntries = Object.entries(greeks).map(([key, value]) => ({ key, value: this.asNum(value) }));
      this.snapshots = snapshots;
      this.loading = false;
      this.cdr.markForCheck();
    });
  }

  private asNum(value: unknown): number {
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
  }
}
