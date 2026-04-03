import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Subject, takeUntil, timer, switchMap, catchError, of } from 'rxjs';
import { MarketApiService } from '../../services/market-api.service';

@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './topbar.component.html',
  styleUrl: './topbar.component.scss',
})
export class TopbarComponent implements OnInit, OnDestroy {
  @Output() menuToggle = new EventEmitter<void>();
  @Output() quickTrade = new EventEmitter<void>();
  @Output() refresh = new EventEmitter<void>();

  searchQuery = '';
  marketPhase = 'closed';
  hasNotifications = false;

  private destroy$ = new Subject<void>();

  constructor(
    private router: Router,
    private marketApi: MarketApiService,
  ) {}

  get marketPhaseLabel(): string {
    const labels: Record<string, string> = {
      open: 'Market Open',
      pre_open: 'Pre-Open',
      post_close: 'Post-Close',
      closed: 'Closed',
      holiday: 'Holiday',
      weekend: 'Weekend',
    };
    return labels[this.marketPhase] ?? this.marketPhase;
  }

  ngOnInit(): void {
    // Poll market status every 60s
    timer(0, 60_000).pipe(
      switchMap(() => this.marketApi.getMarketStatus().pipe(
        catchError(() => of(null)),
      )),
      takeUntil(this.destroy$),
    ).subscribe(status => {
      if (status) {
        this.marketPhase = status.phase;
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  onSearchInput(event: Event): void {
    this.searchQuery = (event.target as HTMLInputElement).value;
  }

  onSearchSubmit(): void {
    const q = this.searchQuery.trim().toUpperCase();
    if (q) {
      this.router.navigate(['/chart', q]);
      this.searchQuery = '';
    }
  }
}
