import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subject, takeUntil, catchError, of, switchMap, map } from 'rxjs';

import { AdminApiService } from '../../services/admin-api.service';
import { AuthService } from '../../services/auth.service';
import { NotificationService } from '../../services/notification.service';
import { ModelStatus } from '../../core/models';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  BadgeVariant,
} from '../../shared';

@Component({
  selector: 'app-sys-models',
  standalone: true,
  imports: [CommonModule, StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent],
  templateUrl: './sys-models.component.html',
  styleUrl: './sys-models.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SysModelsComponent implements OnInit, OnDestroy {
  model: ModelStatus | null = null;
  loading = true;
  reloading = false;
  retraining = false;

  private destroy$ = new Subject<void>();

  constructor(
    private cdr: ChangeDetectorRef,
    private adminApi: AdminApiService,
    public auth: AuthService,
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
    switch (this.model.status) {
      case 'loaded': return 'success';
      case 'loading': return 'running';
      default: return 'error';
    }
  }

  load(): void {
    this.loading = true;
    this.cdr.markForCheck();
    this.adminApi.getModelStatus().pipe(
      catchError(() => of(null)),
      switchMap((status) => {
        const hasModel = !!status?.model_version && status.model_version !== 'none';
        if (hasModel) return of(status);
        return this.adminApi.getRegistryVersions().pipe(
          map((versions) => {
            if (!versions.length) return status;
            const active = versions.find(v => v.status === 'active') || versions[0];
            return {
              model_version: active.version,
              status: status?.status || 'loaded',
              last_trained: active.created_at || null,
              accuracy: active.accuracy ?? null,
              executed_trade_win_rate: active.executed_trade_win_rate ?? null,
            } as ModelStatus;
          }),
          catchError(() => of(status)),
        );
      }),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      this.model = s;
      this.loading = false;
      this.cdr.markForCheck();
    });
  }

  reload(): void {
    this.reloading = true;
    this.cdr.markForCheck();
    this.adminApi.reloadModel().pipe(
      catchError(() => { this.notify.error('Reload failed.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.reloading = false;
      if (res) this.notify.success(res.message);
      this.load();
    });
  }

  retrain(): void {
    this.retraining = true;
    this.cdr.markForCheck();
    this.adminApi.triggerRetrain().pipe(
      catchError(() => { this.notify.error('Retrain failed.'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.retraining = false;
      if (res) this.notify.success('Retrain triggered.');
      this.load();
    });
  }
}
