import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, takeUntil, catchError, of } from 'rxjs';

import { IntradayApiService } from '../../services/intraday-api.service';
import { NotificationService } from '../../services/notification.service';
import { IntradayOptionSignal } from '../../core/models';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  BadgeVariant,
} from '../../shared';

@Component({
  selector: 'app-intra-options',
  standalone: true,
  imports: [CommonModule, FormsModule, StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent],
  templateUrl: './intra-options.component.html',
  styleUrl: './intra-options.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class IntraOptionsComponent implements OnInit, OnDestroy {
  symbol = 'NIFTY';
  underlyingPrice = 24500;
  underlyingTrend = 'bullish';
  trendConfidence = 0.7;

  signal: IntradayOptionSignal | null = null;
  loading = false;

  private destroy$ = new Subject<void>();

  constructor(
    private cdr: ChangeDetectorRef,
    private api: IntradayApiService,
    private notify: NotificationService,
  ) {}

  ngOnInit(): void {}

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  signalBadge(): BadgeVariant {
    if (!this.signal) return 'neutral';
    if (this.signal.signal_type === 'NO_TRADE') return 'error';
    if (this.signal.confidence >= 0.6) return 'success';
    return 'running';
  }

  generate(): void {
    this.loading = true;
    this.cdr.markForCheck();
    this.api.getOptionSignal({
      symbol: this.symbol,
      underlying_trend: this.underlyingTrend,
      trend_confidence: this.trendConfidence,
      underlying_price: this.underlyingPrice,
    }).pipe(
      catchError(() => { this.notify.error('Failed to generate option signal.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      this.signal = s;
      this.loading = false;
      this.cdr.markForCheck();
    });
  }
}
