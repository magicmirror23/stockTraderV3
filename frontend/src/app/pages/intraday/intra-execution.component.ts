import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subject, takeUntil, catchError, of, forkJoin } from 'rxjs';

import { IntradayApiService } from '../../services/intraday-api.service';
import { NotificationService } from '../../services/notification.service';
import { IntradayExecutionStats, OpenPosition } from '../../core/models';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  PnlDisplayComponent, BadgeVariant,
} from '../../shared';

@Component({
  selector: 'app-intra-execution',
  standalone: true,
  imports: [
    CommonModule, StatCardComponent, StateBadgeComponent,
    LoadingSkeletonComponent, PnlDisplayComponent,
  ],
  templateUrl: './intra-execution.component.html',
  styleUrl: './intra-execution.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class IntraExecutionComponent implements OnInit, OnDestroy {
  stats: IntradayExecutionStats | null = null;
  positions: OpenPosition[] = [];
  loading = true;
  closingAll = false;

  private destroy$ = new Subject<void>();

  constructor(
    private cdr: ChangeDetectorRef,
    private api: IntradayApiService,
    private notify: NotificationService,
  ) {}

  ngOnInit(): void {
    this.load();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  pnlBadge(): BadgeVariant {
    if (!this.stats) return 'neutral';
    return this.stats.total_pnl >= 0 ? 'success' : 'error';
  }

  load(): void {
    this.loading = true;
    this.cdr.markForCheck();
    forkJoin({
      stats: this.api.getExecutionStats().pipe(catchError(() => of(null))),
      pos: this.api.getOpenPositions().pipe(catchError(() => of({ count: 0, positions: [] }))),
    }).pipe(takeUntil(this.destroy$)).subscribe(({ stats, pos }) => {
      this.stats = stats;
      this.positions = pos?.positions ?? [];
      this.loading = false;
      this.cdr.markForCheck();
    });
  }

  forceCloseAll(): void {
    this.closingAll = true;
    this.cdr.markForCheck();
    this.api.forceCloseAll().pipe(
      catchError(() => { this.notify.error('Force close failed.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.closingAll = false;
      if (res) this.notify.success(`Closed ${res.closed_count} positions. PnL: ₹${res.total_pnl.toFixed(2)}`);
      this.load();
    });
  }
}
