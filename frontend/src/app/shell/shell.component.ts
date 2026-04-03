import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { Subject, takeUntil, timer, switchMap, catchError, of } from 'rxjs';
import { SidebarComponent } from './sidebar/sidebar.component';
import { TopbarComponent } from './topbar/topbar.component';
import { FooterComponent } from './footer/footer.component';
import { MarketApiService } from '../services/market-api.service';
import { LiveStreamService } from '../services/live-stream.service';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    SidebarComponent,
    TopbarComponent,
    FooterComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent implements OnInit, OnDestroy {
  sidebarCollapsed = false;
  mobileMenuOpen = false;
  marketPhase = 'closed';
  wsConnected = false;
  apiStatus = 'ok';

  private destroy$ = new Subject<void>();

  constructor(
    private router: Router,
    private marketApi: MarketApiService,
    private liveStream: LiveStreamService,
  ) {}

  ngOnInit(): void {
    // Track WebSocket connection state
    this.liveStream.connected$.pipe(
      takeUntil(this.destroy$),
    ).subscribe(c => this.wsConnected = c);

    // Poll market status every 60s for footer
    timer(0, 60_000).pipe(
      switchMap(() => this.marketApi.getMarketStatus().pipe(
        catchError(() => of(null)),
      )),
      takeUntil(this.destroy$),
    ).subscribe(status => {
      if (status) {
        this.marketPhase = status.phase;
        this.apiStatus = 'ok';
      } else {
        this.apiStatus = 'error';
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  onQuickTrade(): void {
    this.router.navigate(['/trading']);
  }

  onRefresh(): void {
    // Simple page reload trigger — pages can listen via a shared service later
    window.location.reload();
  }
}
