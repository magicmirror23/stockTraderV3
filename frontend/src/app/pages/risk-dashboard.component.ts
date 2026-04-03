// Risk dashboard page component
import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RiskApiService, RiskStatus } from '../services/risk-api.service';

@Component({
  selector: 'app-risk-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="page">
      <h1>Risk Dashboard</h1>

      <!-- Risk Status Card -->
      <div class="card mb-2">
        <h2>Risk Engine Status</h2>
        <div *ngIf="!status" class="text-muted text-sm">Loading...</div>
        <div *ngIf="status" class="grid-4">
          <div class="stat-card">
            <div class="stat-label">Capital</div>
            <div class="stat-value">₹{{ status.capital | number:'1.0-0' }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Used Capital</div>
            <div class="stat-value">₹{{ status.used_capital | number:'1.0-0' }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Daily P&L</div>
            <div class="stat-value" [ngClass]="(status.daily_pnl || 0) >= 0 ? 'text-success' : 'text-danger'">
              ₹{{ status.daily_pnl | number:'1.2-2' }}
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Open Positions</div>
            <div class="stat-value">{{ status.open_positions }}</div>
          </div>
        </div>

        <div *ngIf="status" class="flex gap-1 mt-1">
          <span class="badge" [ngClass]="status.circuit_breaker_active ? 'badge-danger' : 'badge-success'">
            Circuit Breaker: {{ status.circuit_breaker_active ? 'ACTIVE' : 'OK' }}
          </span>
          <span class="badge" [ngClass]="status.daily_loss_lockout ? 'badge-danger' : 'badge-success'">
            Daily Loss Lockout: {{ status.daily_loss_lockout ? 'LOCKED' : 'OK' }}
          </span>
        </div>
      </div>

      <div class="flex gap-2" style="align-items: flex-start;">
        <!-- Sector Exposure -->
        <div class="card" style="flex:1;">
          <h2>Sector Exposure</h2>
          <div *ngIf="!sectorExposure" class="text-muted text-sm">Loading...</div>
          <div *ngFor="let item of sectorEntries" class="exposure-row">
            <div class="flex justify-between items-center">
              <span class="label">{{ item.key }}</span>
              <span class="value">{{ item.value | number:'1.1-1' }}%</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" [style.width.%]="item.value" [ngClass]="item.value > 25 ? 'bar-danger' : item.value > 15 ? 'bar-warn' : 'bar-ok'"></div>
            </div>
          </div>
          <div *ngIf="sectorExposure && sectorEntries.length === 0" class="text-muted text-sm">No exposure data.</div>
        </div>

        <!-- Portfolio Greeks -->
        <div class="card" style="flex:1;">
          <h2>Portfolio Greeks</h2>
          <div *ngIf="!greeks" class="text-muted text-sm">Loading...</div>
          <div *ngIf="greeks" class="grid-2">
            <div *ngFor="let g of greeksEntries" class="stat-card">
              <div class="stat-label">{{ g.key }}</div>
              <div class="stat-value">{{ g.value | number:'1.4-4' }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Risk Snapshots -->
      <div class="card mt-2">
        <h2>Recent Risk Snapshots</h2>
        <div *ngIf="!snapshots" class="text-muted text-sm">Loading...</div>
        <table *ngIf="snapshots?.length">
          <thead>
            <tr><th>Time</th><th>Type</th><th>Details</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let s of snapshots">
              <td class="text-mono text-sm">{{ s.timestamp }}</td>
              <td><span class="badge badge-info">{{ s.snapshot_type }}</span></td>
              <td class="text-sm">{{ s.data | json }}</td>
            </tr>
          </tbody>
        </table>
        <div *ngIf="snapshots?.length === 0" class="text-muted text-sm">No snapshots yet.</div>
      </div>
    </div>
  `,
  styles: [`
    .exposure-row { margin-bottom: 10px; }
    .exposure-row .label { font-weight: 500; }
    .exposure-row .value { font-weight: 600; font-family: var(--font-mono); }
    .bar-track { height: 8px; background: var(--color-border); border-radius: 4px; margin-top: 4px; }
    .bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
    .bar-ok { background: #16a34a; }
    .bar-warn { background: #f59e0b; }
    .bar-danger { background: #dc2626; }
    .text-success { color: #16a34a; }
    .text-danger { color: #dc2626; }
    .badge-danger { background: #fee2e2; color: #991b1b; }
    .badge-success { background: #dcfce7; color: #166534; }
    .badge-info { background: #dbeafe; color: #1e40af; }
    .mt-1 { margin-top: 0.75rem; }
    .grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
    @media (max-width: 900px) {
      :host .flex.gap-2 { flex-direction: column; }
    }
  `]
})
export class RiskDashboardComponent implements OnInit, OnDestroy {
  status: RiskStatus | null = null;
  sectorExposure: Record<string, number> | null = null;
  greeks: Record<string, number> | null = null;
  snapshots: any[] | null = null;

  sectorEntries: { key: string; value: number }[] = [];
  greeksEntries: { key: string; value: number }[] = [];

  private timer: any;

  constructor(private riskApi: RiskApiService) {}

  ngOnInit(): void {
    this.loadAll();
    this.timer = setInterval(() => this.loadAll(), 15_000);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  loadAll(): void {
    this.riskApi.getStatus().subscribe({ next: s => this.status = s, error: () => {} });
    this.riskApi.getSectorExposure().subscribe({
      next: d => {
        this.sectorExposure = d;
        this.sectorEntries = Object.entries(d).map(([key, value]) => ({ key, value })).sort((a, b) => b.value - a.value);
      },
      error: () => {}
    });
    this.riskApi.getPortfolioGreeks().subscribe({
      next: d => {
        this.greeks = d;
        this.greeksEntries = Object.entries(d).map(([key, value]) => ({ key, value }));
      },
      error: () => {}
    });
    this.riskApi.getSnapshots().subscribe({ next: d => this.snapshots = d, error: () => {} });
  }
}
