// Execution quality page component
import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ExecutionApiService } from '../services/execution-api.service';

@Component({
  selector: 'app-execution-quality',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="page">
      <h1>Execution Quality</h1>

      <!-- Stats -->
      <div class="card mb-2">
        <h2>Execution Statistics</h2>
        <div *ngIf="!stats" class="text-muted text-sm">Loading...</div>
        <div *ngIf="stats" class="grid-4">
          <div *ngFor="let s of statsEntries" class="stat-card">
            <div class="stat-label">{{ formatLabel(s.key) }}</div>
            <div class="stat-value">{{ formatValue(s.value) }}</div>
          </div>
        </div>
      </div>

      <!-- Recent Reports -->
      <div class="card">
        <div class="flex justify-between items-center mb-1">
          <h2>Recent Execution Reports</h2>
          <button class="btn-primary btn-sm" (click)="loadAll()">Refresh</button>
        </div>
        <div *ngIf="!reports" class="text-muted text-sm">Loading...</div>
        <div *ngIf="reports?.length === 0" class="text-muted text-sm">No execution reports yet.</div>
        <table *ngIf="reports?.length">
          <thead>
            <tr>
              <th>Ticker</th><th>Side</th><th>Order Type</th><th>Quantity</th>
              <th>Signal</th><th>Fill</th><th>Slippage</th><th>Quality</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let r of reports">
              <td><strong>{{ r.ticker }}</strong></td>
              <td><span class="badge" [ngClass]="r.side === 'buy' ? 'badge-buy' : 'badge-sell'">{{ r.side }}</span></td>
              <td>{{ r.order_type }}</td>
              <td>{{ r.quantity }}</td>
              <td class="text-mono">₹{{ r.signal_price }}</td>
              <td class="text-mono">₹{{ r.fill_price || '—' }}</td>
              <td class="text-mono" [ngClass]="(r.slippage_pct || 0) > 0.5 ? 'text-danger' : 'text-success'">
                {{ r.slippage_pct | number:'1.3-3' }}%
              </td>
              <td>
                <span class="badge" [ngClass]="{
                  'badge-success': r.quality_score >= 0.8,
                  'badge-warning': r.quality_score >= 0.5 && r.quality_score < 0.8,
                  'badge-danger': r.quality_score < 0.5
                }">{{ r.quality_score | number:'1.2-2' }}</span>
              </td>
              <td>
                <span class="badge" [ngClass]="r.status === 'filled' ? 'badge-success' : r.status === 'rejected' ? 'badge-danger' : 'badge-info'">
                  {{ r.status }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  styles: [`
    .badge-buy { background: #dcfce7; color: #166534; }
    .badge-sell { background: #fee2e2; color: #991b1b; }
    .badge-success { background: #dcfce7; color: #166534; }
    .badge-danger { background: #fee2e2; color: #991b1b; }
    .badge-warning { background: #fef3c7; color: #92400e; }
    .badge-info { background: #dbeafe; color: #1e40af; }
    .text-success { color: #16a34a; }
    .text-danger { color: #dc2626; }
  `]
})
export class ExecutionQualityComponent implements OnInit, OnDestroy {
  stats: any | null = null;
  statsEntries: { key: string; value: any }[] = [];
  reports: any[] | null = null;

  private timer: any;

  constructor(private execApi: ExecutionApiService) {}

  ngOnInit(): void {
    this.loadAll();
    this.timer = setInterval(() => this.loadAll(), 15_000);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  loadAll(): void {
    this.execApi.getStats().subscribe({
      next: s => {
        this.stats = s;
        this.statsEntries = Object.entries(s || {}).map(([key, value]) => ({ key, value }));
      },
      error: () => {}
    });
    this.execApi.getRecentReports().subscribe({ next: d => this.reports = d, error: () => {} });
  }

  formatLabel(key: string): string {
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  formatValue(val: any): string {
    if (typeof val === 'number') return val % 1 === 0 ? val.toString() : val.toFixed(3);
    return String(val);
  }
}
