import {
  Component, ChangeDetectionStrategy, ChangeDetectorRef,
  OnInit, OnDestroy,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, takeUntil, timer, catchError, of } from 'rxjs';

import { MarketApiService } from '../services/market-api.service';
import { NotificationService } from '../services/notification.service';
import { MarketStatus, AccountProfile } from '../core/models/market.model';
import { BotStatus, BotConfig } from '../core/models/bot.model';

import {
  StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
  EmptyStateComponent, ConfirmDialogComponent,
  StatCardConfig, BadgeVariant, ConfirmDialogConfig,
} from '../shared';

@Component({
  selector: 'app-bot-panel',
  standalone: true,
  imports: [
    CommonModule, FormsModule, DatePipe,
    StatCardComponent, StateBadgeComponent, LoadingSkeletonComponent,
    EmptyStateComponent, ConfirmDialogComponent,
  ],
  templateUrl: './bot-panel.component.html',
  styleUrl: './bot-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BotPanelComponent implements OnInit, OnDestroy {
  // Market
  market: MarketStatus | null = null;
  account: AccountProfile | null = null;
  accountLoading = false;

  // Bot
  botStatus: BotStatus | null = null;
  botRunning = false;
  starting = false;
  stopping = false;

  // Config
  watchlistStr = 'RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK';
  botConfig: BotConfig = {
    min_confidence: 0.7,
    max_positions: 5,
    position_size: 10000,
    stop_loss_pct: 0.02,
    take_profit_pct: 0.05,
    cycle_interval: 60,
  };

  // Confirm
  showConfirm = false;
  confirmConfig: ConfirmDialogConfig = { title: '', message: '' };
  pendingAction: 'start' | 'stop' | null = null;

  // Computed from bot
  positionEntries: { key: string; value: any }[] = [];
  credentialsList: { key: string; set: boolean }[] = [];
  credentialSources: { key: string; source: string }[] = [];
  countdownStr = '';
  private secondsLeft = 0;

  loading = true;

  private destroy$ = new Subject<void>();

  constructor(
    private cdr: ChangeDetectorRef,
    private marketApi: MarketApiService,
    private notify: NotificationService,
  ) {}

  ngOnInit(): void {
    this.loadMarket();
    this.loadAccount('auto');
    this.loadBotStatus();
    timer(30_000, 30_000).pipe(takeUntil(this.destroy$)).subscribe(() => this.loadMarket());
    timer(5_000, 5_000).pipe(takeUntil(this.destroy$)).subscribe(() => this.loadBotStatus());
    timer(1_000, 1_000).pipe(takeUntil(this.destroy$)).subscribe(() => this.tickCountdown());
  }

  ngOnDestroy(): void {
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
      case 'open': return 'OPEN';
      case 'pre_open': return 'PRE-OPEN';
      default: return 'CLOSED';
    }
  }

  get botStateBadge(): BadgeVariant {
    if (this.botStatus?.state === 'SAFE_MODE' || this.botStatus?.state === 'ERROR') return 'danger';
    if (this.botRunning && !this.botStatus?.paused) return 'running';
    if (this.botStatus?.paused) return 'warning';
    return 'stopped';
  }

  get botStateLabel(): string {
    if (this.botStatus?.state) return this.botStatus.state;
    if (this.botRunning && !this.botStatus?.paused) return 'RUNNING';
    if (this.botStatus?.paused) return 'PAUSED';
    return 'STOPPED';
  }

  get pnlCards(): StatCardConfig[] {
    if (!this.botStatus) return [];
    return [
      {
        label: 'Total P&L', value: `₹${(this.botStatus.total_pnl ?? 0).toLocaleString()}`,
        icon: 'graph-up-arrow', trend: (this.botStatus.total_pnl ?? 0) >= 0 ? 'up' : 'down',
      },
      { label: 'Trades Today', value: this.botStatus.trades_today?.length ?? 0, icon: 'arrow-left-right' },
      { label: 'Cycles Run', value: this.botStatus.cycle_count ?? 0, icon: 'arrow-repeat' },
      { label: 'Active Positions', value: this.botStatus.active_positions ?? 0, icon: 'stack' },
    ];
  }

  // ── Actions ──
  loadAccount(mode: 'auto' | 'live' = 'auto'): void {
    this.accountLoading = true;
    this.cdr.markForCheck();
    this.marketApi.getAccountProfile(mode).pipe(
      catchError(() => { this.notify.error('Failed to verify account'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(a => {
      this.accountLoading = false;
      if (a) {
        this.account = a;
        this.credentialsList = a.credentials_set
          ? Object.entries(a.credentials_set).map(([key, set]) => ({ key, set }))
          : [];
        this.credentialSources = a.credentials_source
          ? Object.entries(a.credentials_source).map(([key, source]) => ({ key, source }))
          : [];
      }
      this.cdr.markForCheck();
    });
  }

  confirmStart(): void {
    this.pendingAction = 'start';
    this.confirmConfig = {
      title: 'Start Bot',
      message: `Start auto-trading with ${this.watchlistStr.split(',').length} symbols, ₹${this.botConfig.position_size} position size?`,
      severity: 'warning',
      confirmLabel: 'Start Bot',
    };
    this.showConfirm = true;
    this.cdr.markForCheck();
  }

  confirmStop(): void {
    this.pendingAction = 'stop';
    this.confirmConfig = {
      title: 'Stop Bot',
      message: 'Stop the auto-trading bot? All pending cycles will be cancelled.',
      severity: 'danger',
      confirmLabel: 'Stop Bot',
    };
    this.showConfirm = true;
    this.cdr.markForCheck();
  }

  onConfirm(): void {
    this.showConfirm = false;
    if (this.pendingAction === 'start') this.startBot();
    else if (this.pendingAction === 'stop') this.stopBot();
    this.pendingAction = null;
  }

  onCancelConfirm(): void {
    this.showConfirm = false;
    this.pendingAction = null;
    this.cdr.markForCheck();
  }

  grantConsent(): void {
    this.marketApi.botConsent(true).pipe(
      catchError(() => { this.notify.error('Failed to grant consent'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      if (res) this.notify.success((res as Record<string, string>)['message'] || 'Trading resumed');
      this.loadBotStatus();
    });
  }

  declineConsent(): void {
    this.marketApi.botConsent(false).pipe(
      catchError(() => { this.notify.error('Failed to decline'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      if (res) {
        this.botRunning = false;
        this.notify.success((res as Record<string, string>)['message'] || 'Bot stopped');
      }
      this.loadBotStatus();
    });
  }

  // ── Private ──
  private startBot(): void {
    this.starting = true;
    this.cdr.markForCheck();
    const desiredPositionSize = Math.max(1_000, Number(this.botConfig.position_size ?? 10_000));
    const available = Math.max(1, Number(this.botStatus?.available_balance ?? 100_000));
    const positionSizePct = Math.min(0.5, Math.max(0.01, desiredPositionSize / available));
    const config = {
      ...this.botConfig,
      position_size_pct: positionSizePct,
      watchlist: this.watchlistStr.split(',').map(t => t.trim()).filter(t => t),
    };
    this.marketApi.startBot(config).pipe(
      catchError(() => { this.notify.error('Failed to start bot'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.starting = false;
      if (res) {
        this.botRunning = true;
        this.notify.success((res as Record<string, string>)['message'] || 'Bot started');
      }
      this.loadBotStatus();
      this.cdr.markForCheck();
    });
  }

  private stopBot(): void {
    this.stopping = true;
    this.cdr.markForCheck();
    this.marketApi.stopBot().pipe(
      catchError(() => { this.notify.error('Failed to stop bot'); return of(null); }),
      takeUntil(this.destroy$),
    ).subscribe(res => {
      this.stopping = false;
      if (res) {
        this.botRunning = false;
        this.notify.success((res as Record<string, string>)['message'] || 'Bot stopped');
      }
      this.loadBotStatus();
      this.cdr.markForCheck();
    });
  }

  private loadMarket(): void {
    this.marketApi.getMarketStatus().pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(m => {
      if (m) {
        this.market = m;
        this.secondsLeft = m.seconds_to_next;
      }
      this.loading = false;
      this.cdr.markForCheck();
    });
  }

  private loadBotStatus(): void {
    this.marketApi.getBotStatus().pipe(
      catchError(() => of(null)),
      takeUntil(this.destroy$),
    ).subscribe(s => {
      if (s) {
        const normalized = this.normalizeBotStatus(s);
        this.botStatus = normalized;
        this.botRunning = normalized.running;
        this.positionEntries = Object.entries(normalized.positions || {}).map(([key, value]) => ({ key, value }));

        if (normalized.watchlist?.length) {
          this.watchlistStr = normalized.watchlist.join(', ');
        }
        if (normalized.min_confidence != null) {
          this.botConfig.min_confidence = normalized.min_confidence;
        }
        if (normalized.max_positions != null) {
          this.botConfig.max_positions = normalized.max_positions;
        }
        if (normalized.position_size != null) {
          this.botConfig.position_size = normalized.position_size;
        }
        if (normalized.stop_loss_pct != null) {
          this.botConfig.stop_loss_pct = normalized.stop_loss_pct;
        }
        if (normalized.take_profit_pct != null) {
          this.botConfig.take_profit_pct = normalized.take_profit_pct;
        }
        if (normalized.cycle_interval != null) {
          this.botConfig.cycle_interval = normalized.cycle_interval;
        }
      }
      this.cdr.markForCheck();
    });
  }

  private normalizeBotStatus(raw: any): BotStatus {
    const state = typeof raw?.state === 'string' ? raw.state : '';
    const running = typeof raw?.running === 'boolean'
      ? raw.running
      : ['ACTIVE', 'PAUSED', 'WAITING_FOR_MARKET', 'WAITING_FOR_CONSENT', 'SAFE_MODE'].includes(state);
    const paused = typeof raw?.paused === 'boolean'
      ? raw.paused
      : ['PAUSED', 'WAITING_FOR_MARKET', 'WAITING_FOR_CONSENT'].includes(state);
    const consentPending = typeof raw?.consent_pending === 'boolean'
      ? raw.consent_pending
      : state === 'WAITING_FOR_CONSENT';
    const watchlist = Array.isArray(raw?.watchlist)
      ? raw.watchlist
      : Array.isArray(raw?.config?.watchlist) ? raw.config.watchlist : [];

    return {
      ...raw,
      state,
      running,
      paused,
      consent_pending: consentPending,
      auto_resume_in: raw?.auto_resume_in ?? raw?.consent_countdown ?? null,
      watchlist,
      min_confidence: raw?.min_confidence ?? raw?.config?.min_confidence ?? this.botConfig.min_confidence ?? 0.7,
      max_positions: raw?.max_positions ?? raw?.config?.max_positions ?? this.botConfig.max_positions ?? 5,
      position_size: raw?.position_size
        ?? Math.round((raw?.position_size_pct ?? raw?.config?.position_size_pct ?? 0.1) * (raw?.available_balance ?? 100000)),
      stop_loss_pct: raw?.stop_loss_pct ?? raw?.config?.stop_loss_pct ?? this.botConfig.stop_loss_pct ?? 0.02,
      take_profit_pct: raw?.take_profit_pct ?? raw?.config?.take_profit_pct ?? this.botConfig.take_profit_pct ?? 0.05,
      cycle_interval: raw?.cycle_interval ?? raw?.config?.cycle_interval ?? this.botConfig.cycle_interval ?? 60,
      cycle_count: raw?.cycle_count ?? 0,
      last_cycle: raw?.last_cycle ?? null,
      active_positions: raw?.active_positions ?? Object.keys(raw?.positions || {}).length,
      positions: raw?.positions || {},
      trades_today: raw?.trades_today || [],
      total_pnl: raw?.total_pnl ?? 0,
      errors: raw?.errors || [],
    };
  }

  private tickCountdown(): void {
    if (this.secondsLeft > 0) {
      this.secondsLeft--;
      const h = Math.floor(this.secondsLeft / 3600);
      const m = Math.floor((this.secondsLeft % 3600) / 60);
      const s = this.secondsLeft % 60;
      this.countdownStr = h > 0
        ? `${h}h ${m}m ${s}s`
        : m > 0 ? `${m}m ${s}s` : `${s}s`;
      this.cdr.markForCheck();
    }
  }
}

