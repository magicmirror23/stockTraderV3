import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subject, takeUntil, catchError, of } from 'rxjs';

import { IntradayApiService } from '../../services/intraday-api.service';
import { NotificationService } from '../../services/notification.service';
import { SupervisorStatus } from '../../core/models';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  PnlDisplayComponent, BadgeVariant,
} from '../../shared';

@Component({
  selector: 'app-intra-supervisor',
  standalone: true,
  imports: [
    CommonModule, StatCardComponent, StateBadgeComponent,
    LoadingSkeletonComponent, PnlDisplayComponent,
  ],
  templateUrl: './intra-supervisor.component.html',
  styleUrl: './intra-supervisor.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class IntraSupervisorComponent implements OnInit, OnDestroy {
  status: SupervisorStatus | null = null;
  loading = true;
  pausing = false;
  resuming = false;
  halting = false;

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

  stateBadge(): BadgeVariant {
    if (!this.status) return 'neutral';
    switch (this.status.state) {
      case 'ACTIVE': return 'success';
      case 'PAUSED': case 'COOLDOWN': return 'running';
      case 'HALTED': return 'error';
      default: return 'neutral';
    }
  }

  drawdownBadge(): BadgeVariant {
    if (!this.status) return 'neutral';
    if (this.status.drawdown_pct >= 4) return 'error';
    if (this.status.drawdown_pct >= 2) return 'running';
    return 'success';
  }

  cooldownSymbols(): string[] {
    return this.status?.cooldowns ? Object.keys(this.status.cooldowns) : [];
  }

  load(): void {
    this.loading = true;
    this.cdr.markForCheck();
    this.api.getSupervisorStatus().pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      this.status = s;
      this.loading = false;
      this.cdr.markForCheck();
    });
  }

  pause(): void {
    this.pausing = true;
    this.cdr.markForCheck();
    this.api.pauseTrading().pipe(
      catchError(() => { this.notify.error('Pause failed.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.pausing = false;
      if (res) this.notify.success('Trading paused.');
      this.load();
    });
  }

  resume(): void {
    this.resuming = true;
    this.cdr.markForCheck();
    this.api.resumeTrading().pipe(
      catchError(() => { this.notify.error('Resume failed.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.resuming = false;
      if (res) this.notify.success('Trading resumed.');
      this.load();
    });
  }

  halt(): void {
    this.halting = true;
    this.cdr.markForCheck();
    this.api.haltTrading('manual_dashboard').pipe(
      catchError(() => { this.notify.error('Halt failed.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.halting = false;
      if (res) this.notify.success('Trading HALTED.');
      this.load();
    });
  }
}
