import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subject, takeUntil, catchError, of } from 'rxjs';

import { PredictionApiService } from '../services/prediction-api.service';
import { NotificationService } from '../services/notification.service';
import { PredictionResult } from '../core/models/prediction.model';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  EmptyStateComponent, BadgeVariant, StatCardConfig,
} from '../shared';

@Component({
  selector: 'app-signal-explorer',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterLink,
    StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent, EmptyStateComponent,
  ],
  templateUrl: './signal-explorer.component.html',
  styleUrl: './signal-explorer.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SignalExplorerComponent implements OnInit, OnDestroy {
  // Filters
  ticker = 'RELIANCE';
  horizon = '1d';
  batchInput = 'RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK';
  filterAction: string = 'all';

  // State
  signals: PredictionResult[] = [];
  loading = false;
  batchLoading = false;

  // Summary stats
  summaryCards: StatCardConfig[] = [];

  private destroy$ = new Subject<void>();

  constructor(
    private cdr: ChangeDetectorRef,
    private predictionApi: PredictionApiService,
    private notify: NotificationService,
  ) {}

  ngOnInit(): void {
    this.fetchBatch();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ── Computed ──
  get filteredSignals(): PredictionResult[] {
    if (this.filterAction === 'all') return this.signals;
    return this.signals.filter(s => s.action === this.filterAction);
  }

  get buyCount(): number { return this.signals.filter(s => s.action === 'buy').length; }
  get sellCount(): number { return this.signals.filter(s => s.action === 'sell').length; }
  get holdCount(): number { return this.signals.filter(s => s.action === 'hold').length; }

  actionBadge(action: string): BadgeVariant {
    switch (action) {
      case 'buy': return 'buy';
      case 'sell': return 'sell';
      default: return 'hold';
    }
  }

  confidenceClass(c: number): string {
    if (c >= 0.8) return 'se__conf--high';
    if (c >= 0.6) return 'se__conf--mid';
    return 'se__conf--low';
  }

  // ── Actions ──
  fetchSingle(): void {
    if (!this.ticker.trim()) return;
    this.loading = true;
    this.cdr.markForCheck();

    this.predictionApi.predict(this.ticker.trim(), this.horizon).pipe(
      catchError(() => { this.notify.error('Prediction failed'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(result => {
      this.loading = false;
      if (result) {
        const idx = this.signals.findIndex(s => s.ticker === result.ticker);
        if (idx >= 0) this.signals[idx] = result;
        else this.signals = [result, ...this.signals];
        this.updateSummary();
      }
      this.cdr.markForCheck();
    });
  }

  fetchBatch(): void {
    const tickers = this.batchInput.split(',').map(t => t.trim()).filter(t => t);
    if (tickers.length === 0) return;
    this.batchLoading = true;
    this.cdr.markForCheck();

    this.predictionApi.batchPredict(tickers).pipe(
      catchError(() => { this.notify.error('Batch prediction failed'); return of([] as PredictionResult[]); }),
      takeUntil(this.destroy$),
    ).subscribe(results => {
      this.batchLoading = false;
      this.signals = results;
      this.updateSummary();
      if (results.length) this.notify.success(`${results.length} predictions loaded`);
      this.cdr.markForCheck();
    });
  }

  setFilter(action: string): void {
    this.filterAction = action;
    this.cdr.markForCheck();
  }

  trackByTicker(_: number, s: PredictionResult): string { return s.ticker; }

  private updateSummary(): void {
    const avg = this.signals.length
      ? this.signals.reduce((a, s) => a + s.confidence, 0) / this.signals.length
      : 0;
    const avgReturn = this.signals.length
      ? this.signals.reduce((a, s) => a + s.expected_return, 0) / this.signals.length
      : 0;

    this.summaryCards = [
      { label: 'Total Signals', value: this.signals.length, icon: 'bullseye' },
      { label: 'Buy', value: this.buyCount, icon: 'arrow-up-circle', trend: 'up' },
      { label: 'Sell', value: this.sellCount, icon: 'arrow-down-circle', trend: 'down' },
      { label: 'Avg Confidence', value: `${(avg * 100).toFixed(1)}%`, icon: 'speedometer2' },
      { label: 'Avg Exp. Return', value: `${(avgReturn * 100).toFixed(2)}%`, icon: 'graph-up-arrow', trend: avgReturn >= 0 ? 'up' : 'down' },
    ];
  }
}
