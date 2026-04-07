import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subject, takeUntil, catchError, of } from 'rxjs';

import { IntradayApiService } from '../../services/intraday-api.service';
import { NotificationService } from '../../services/notification.service';
import { IntradayModelStatus, IntradayTrainStatus } from '../../core/models';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  BadgeVariant,
} from '../../shared';

@Component({
  selector: 'app-intra-models',
  standalone: true,
  imports: [CommonModule, StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent],
  templateUrl: './intra-models.component.html',
  styleUrl: './intra-models.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class IntraModelsComponent implements OnInit, OnDestroy {
  model: IntradayModelStatus | null = null;
  trainStatus: IntradayTrainStatus | null = null;
  loading = true;
  reloading = false;
  training = false;

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

  get statusBadge(): BadgeVariant {
    if (!this.model) return 'neutral';
    return this.model.loaded ? 'success' : 'error';
  }

  get trainBadge(): BadgeVariant {
    if (!this.trainStatus) return 'neutral';
    switch (this.trainStatus.state) {
      case 'running': return 'running';
      case 'completed': return 'success';
      case 'failed': return 'error';
      default: return 'neutral';
    }
  }

  metricKeys(): string[] {
    return this.model?.metrics ? Object.keys(this.model.metrics) : [];
  }

  load(): void {
    this.loading = true;
    this.cdr.markForCheck();
    this.api.getIntradayModelStatus().pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      this.model = s;
      this.loading = false;
      this.cdr.markForCheck();
    });
    this.api.getIntradayTrainStatus().pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      this.trainStatus = s;
      this.cdr.markForCheck();
    });
  }

  reload(): void {
    this.reloading = true;
    this.cdr.markForCheck();
    this.api.reloadIntradayModel().pipe(
      catchError(() => { this.notify.error('Reload failed.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.reloading = false;
      if (res) this.notify.success('Model reloaded: ' + res.version);
      this.load();
    });
  }

  train(): void {
    this.training = true;
    this.cdr.markForCheck();
    this.api.startIntradayTraining().pipe(
      catchError(() => { this.notify.error('Training failed to start.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.training = false;
      if (res) this.notify.success('Intraday training started.');
      this.load();
    });
  }
}
