// Regime & strategy intelligence page component
import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { StrategyApiService, RegimeResult } from '../services/strategy-api.service';

@Component({
  selector: 'app-regime-panel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>Market Regime & Strategy Intelligence</h1>

      <!-- Regime Heatmap -->
      <div class="card mb-2">
        <div class="flex justify-between items-center mb-1">
          <h2>Market Regime Heatmap</h2>
          <button class="btn-primary btn-sm" (click)="loadHeatmap()" [disabled]="heatmapLoading">
            {{ heatmapLoading ? 'Loading...' : 'Refresh' }}
          </button>
        </div>
        <div class="form-group" style="max-width: 500px;">
          <input [(ngModel)]="symbolsStr" placeholder="RELIANCE, TCS, INFY, HDFCBANK (comma-separated)" />
        </div>
        <div *ngIf="!heatmap" class="text-muted text-sm">Enter symbols and click Refresh.</div>
        <div *ngIf="heatmap" class="regime-grid">
          <div *ngFor="let item of heatmapEntries" class="regime-card" [ngClass]="'regime-' + item.regime">
            <div class="regime-symbol">{{ item.symbol }}</div>
            <div class="regime-type">{{ item.regime }}</div>
            <div class="regime-conf">{{ item.confidence | number:'1.0-0' }}% confidence</div>
            <div class="regime-vol text-sm">Vol: {{ item.volatility | number:'1.4-4' }}</div>
          </div>
        </div>
      </div>

      <!-- Single Symbol Detail -->
      <div class="card mb-2">
        <h2>Regime Detail</h2>
        <div class="flex gap-1">
          <div class="form-group" style="flex:1;">
            <input [(ngModel)]="detailSymbol" placeholder="e.g. RELIANCE" />
          </div>
          <button class="btn-primary" (click)="detectRegime()" [disabled]="detailLoading">
            {{ detailLoading ? 'Detecting...' : 'Detect' }}
          </button>
        </div>
        <div *ngIf="regimeDetail" class="mt-1">
          <div class="flex gap-1 items-center mb-1">
            <span class="badge badge-lg" [ngClass]="'regime-badge-' + regimeDetail.regime">{{ regimeDetail.regime }}</span>
            <span class="text-muted">{{ regimeDetail.confidence | number:'1.0-0' }}% confidence</span>
          </div>
          <div class="grid-3">
            <div class="stat-card">
              <div class="stat-label">Volatility</div>
              <div class="stat-value">{{ regimeDetail.volatility | number:'1.4-4' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Trend</div>
              <div class="stat-value">{{ regimeDetail.trend | number:'1.4-4' }}</div>
            </div>
            <div *ngFor="let ind of indicatorEntries" class="stat-card">
              <div class="stat-label">{{ ind.key }}</div>
              <div class="stat-value">{{ ind.value | number:'1.4-4' }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Strategy Decisions -->
      <div class="card mb-2">
        <div class="flex justify-between items-center">
          <h2>Recent Strategy Decisions</h2>
          <div class="flex gap-1">
            <button class="btn-primary btn-sm" (click)="loadDecisions()">Refresh</button>
          </div>
        </div>
        <div *ngIf="!decisions" class="text-muted text-sm">Loading...</div>
        <table *ngIf="decisions?.length">
          <thead>
            <tr><th>Ticker</th><th>Strategy</th><th>Confidence</th><th>Reason</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let d of decisions">
              <td><strong>{{ d.ticker }}</strong></td>
              <td><span class="badge badge-info">{{ d.strategy }}</span></td>
              <td>{{ d.confidence | number:'1.0-0' }}%</td>
              <td class="text-sm">{{ d.reason }}</td>
            </tr>
          </tbody>
        </table>
        <div *ngIf="decisions?.length === 0" class="text-muted text-sm">No decisions yet.</div>
      </div>

      <!-- Strategy Stats -->
      <div class="card">
        <h2>Strategy Statistics</h2>
        <div *ngIf="!stats" class="text-muted text-sm">Loading...</div>
        <div *ngIf="stats" class="grid-3">
          <div *ngFor="let s of statsEntries" class="stat-card">
            <div class="stat-label">{{ s.key }}</div>
            <div class="stat-value">{{ s.value }}</div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .regime-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px;
    }
    .regime-card {
      padding: 14px; border-radius: var(--radius-md); border: 1px solid var(--color-border);
      text-align: center; transition: background var(--transition);
    }
    .regime-card:hover { background: var(--color-surface-hover); }
    .regime-symbol { font-weight: 700; font-size: 1.1rem; margin-bottom: 4px; }
    .regime-type { font-weight: 600; text-transform: capitalize; margin-bottom: 2px; }
    .regime-conf { font-size: 0.85rem; color: var(--color-text-secondary); }
    .regime-trending_up, .regime-badge-trending_up { border-color: #16a34a; color: #16a34a; }
    .regime-trending_down, .regime-badge-trending_down { border-color: #dc2626; color: #dc2626; }
    .regime-high_vol, .regime-badge-high_vol { border-color: #f59e0b; color: #92400e; }
    .regime-crash, .regime-badge-crash { border-color: #dc2626; background: rgba(220,38,38,0.06); color: #991b1b; }
    .regime-range_bound, .regime-badge-range_bound { border-color: #6366f1; color: #4338ca; }
    .badge-lg { padding: 6px 16px; font-size: 1rem; }
    .badge-info { background: #dbeafe; color: #1e40af; }
    .mt-1 { margin-top: 0.75rem; }
  `]
})
export class RegimePanelComponent implements OnInit, OnDestroy {
  symbolsStr = 'RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK';
  heatmap: Record<string, any> | null = null;
  heatmapEntries: { symbol: string; regime: string; confidence: number; volatility: number }[] = [];
  heatmapLoading = false;

  detailSymbol = '';
  regimeDetail: RegimeResult | null = null;
  detailLoading = false;
  indicatorEntries: { key: string; value: number }[] = [];

  decisions: any[] | null = null;
  stats: any | null = null;
  statsEntries: { key: string; value: any }[] = [];

  private timer: any;

  constructor(private strategyApi: StrategyApiService) {}

  ngOnInit(): void {
    this.loadDecisions();
    this.loadStats();
    this.timer = setInterval(() => {
      this.loadDecisions();
      this.loadStats();
    }, 30_000);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  loadHeatmap(): void {
    this.heatmapLoading = true;
    const syms = this.symbolsStr.split(',').map(s => s.trim()).filter(s => s);
    this.strategyApi.regimeHeatmap(syms).subscribe({
      next: d => {
        this.heatmap = d;
        this.heatmapEntries = Object.entries(d).map(([symbol, v]: [string, any]) => ({
          symbol,
          regime: v.regime || 'unknown',
          confidence: (v.confidence || 0) * 100,
          volatility: v.volatility || 0,
        }));
        this.heatmapLoading = false;
      },
      error: () => this.heatmapLoading = false
    });
  }

  detectRegime(): void {
    if (!this.detailSymbol) return;
    this.detailLoading = true;
    this.strategyApi.detectRegime(this.detailSymbol.trim()).subscribe({
      next: r => {
        this.regimeDetail = r;
        this.indicatorEntries = Object.entries(r.indicators || {}).map(([key, value]) => ({ key, value }));
        this.detailLoading = false;
      },
      error: () => this.detailLoading = false
    });
  }

  loadDecisions(): void {
    this.strategyApi.getRecentDecisions().subscribe({ next: d => this.decisions = d, error: () => {} });
  }

  loadStats(): void {
    this.strategyApi.getStats().subscribe({
      next: s => {
        this.stats = s;
        this.statsEntries = Object.entries(s || {}).map(([key, value]) => ({ key, value }));
      },
      error: () => {}
    });
  }
}
