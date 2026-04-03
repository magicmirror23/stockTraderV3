// Options strategy builder page component
import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { OptionsApiService, StrategyRecommendation } from '../services/options-api.service';

@Component({
  selector: 'app-options-builder',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>Options Strategy Builder</h1>

      <div class="flex gap-2" style="align-items: flex-start;">
        <!-- Strategy Selector -->
        <div class="card" style="flex: 1; min-width: 340px;">
          <h2>Build Strategy</h2>

          <div class="form-group">
            <label>Underlying</label>
            <input [(ngModel)]="underlying" placeholder="e.g. NIFTY" />
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>Spot Price</label>
              <input type="number" [(ngModel)]="spot" />
            </div>
            <div class="form-group">
              <label>IV (decimal)</label>
              <input type="number" [(ngModel)]="iv" step="0.01" />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>Expiry (YYYY-MM-DD)</label>
              <input [(ngModel)]="expiry" placeholder="2025-06-26" />
            </div>
            <div class="form-group">
              <label>Lot Size</label>
              <input type="number" [(ngModel)]="lotSize" />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>Direction</label>
              <select [(ngModel)]="direction">
                <option value="bullish">Bullish</option>
                <option value="bearish">Bearish</option>
                <option value="neutral">Neutral</option>
              </select>
            </div>
            <div class="form-group">
              <label>Confidence</label>
              <input type="number" [(ngModel)]="confidence" min="0" max="1" step="0.05" />
            </div>
          </div>

          <div class="btn-group mt-1">
            <button class="btn-primary" (click)="recommend()" [disabled]="loading">
              {{ loading ? 'Loading...' : 'Auto-Recommend' }}
            </button>
          </div>

          <div class="divider"></div>
          <h3>Quick Build</h3>
          <div class="btn-group">
            <button class="btn-secondary" (click)="buildCoveredCall()">Covered Call</button>
            <button class="btn-secondary" (click)="buildBullCallSpread()">Bull Call Spread</button>
            <button class="btn-secondary" (click)="buildIronCondor()">Iron Condor</button>
            <button class="btn-secondary" (click)="buildStraddle()">Long Straddle</button>
          </div>
        </div>

        <!-- Strategy Result -->
        <div style="flex: 1.5; min-width: 400px;">
          <div class="card mb-2" *ngIf="result">
            <h2>
              <span class="badge badge-info">{{ result.strategy_type }}</span>
            </h2>
            <div class="text-sm text-muted mb-1">{{ result.rationale }}</div>

            <div class="grid-3">
              <div class="stat-card">
                <div class="stat-label">Max Profit</div>
                <div class="stat-value text-success">₹{{ result.max_profit | number:'1.0-0' }}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Max Loss</div>
                <div class="stat-value text-danger">₹{{ result.max_loss | number:'1.0-0' }}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Margin Required</div>
                <div class="stat-value">₹{{ result.margin_required | number:'1.0-0' }}</div>
              </div>
            </div>

            <div *ngIf="result.breakeven?.length" class="mt-1 text-sm">
              <strong>Breakeven:</strong>
              <span *ngFor="let b of result.breakeven; let last = last">
                ₹{{ b | number:'1.2-2' }}{{ last ? '' : ', ' }}
              </span>
            </div>

            <!-- Legs Table -->
            <table class="mt-1" *ngIf="result.legs?.length">
              <thead>
                <tr><th>Instrument</th><th>Type</th><th>Strike</th><th>Side</th><th>Qty</th><th>Premium</th></tr>
              </thead>
              <tbody>
                <tr *ngFor="let leg of result.legs">
                  <td>{{ leg.instrument }}</td>
                  <td><span class="badge" [ngClass]="leg.option_type === 'CE' ? 'badge-call' : 'badge-put'">{{ leg.option_type }}</span></td>
                  <td class="text-mono">₹{{ leg.strike | number:'1.0-0' }}</td>
                  <td><span class="badge" [ngClass]="leg.side === 'buy' ? 'badge-buy' : 'badge-sell'">{{ leg.side }}</span></td>
                  <td>{{ leg.quantity }}</td>
                  <td class="text-mono">₹{{ leg.premium | number:'1.2-2' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Payoff Diagram -->
          <div class="card" *ngIf="payoffData?.length">
            <h2>Payoff Diagram</h2>
            <div class="payoff-chart">
              <div *ngFor="let point of payoffData" class="payoff-bar-wrap">
                <div class="payoff-bar"
                     [style.height.px]="getBarHeight(point.payoff)"
                     [style.marginTop.px]="getBarMarginTop(point.payoff)"
                     [ngClass]="point.payoff >= 0 ? 'bar-profit' : 'bar-loss'">
                </div>
                <div class="payoff-label text-xs" *ngIf="payoffData.indexOf(point) % labelInterval === 0">
                  {{ point.spot | number:'1.0-0' }}
                </div>
              </div>
            </div>
          </div>

          <div *ngIf="!result" class="card">
            <div class="text-muted text-center" style="padding: 40px;">
              Select parameters and build a strategy to see results
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .btn-group { display: flex; flex-wrap: wrap; gap: 8px; }
    .btn-secondary {
      background: var(--color-surface-hover); color: var(--color-text);
      border: 1px solid var(--color-border); padding: 8px 16px;
      border-radius: var(--radius-md); cursor: pointer; font-weight: 500;
    }
    .btn-secondary:hover { background: var(--color-border); }
    .divider { border-top: 1px solid var(--color-border); margin: 1rem 0; }
    h3 { font-size: 0.95rem; font-weight: 600; margin-bottom: 8px; color: var(--color-text-secondary); }
    .badge-call { background: #dbeafe; color: #1e40af; }
    .badge-put { background: #fce7f3; color: #9d174d; }
    .badge-buy { background: #dcfce7; color: #166534; }
    .badge-sell { background: #fee2e2; color: #991b1b; }
    .badge-info { background: #dbeafe; color: #1e40af; }
    .text-success { color: #16a34a; }
    .text-danger { color: #dc2626; }
    .mt-1 { margin-top: 0.75rem; }
    .text-center { text-align: center; }
    .payoff-chart {
      display: flex; align-items: flex-end; height: 160px;
      border-bottom: 1px solid var(--color-border); padding-bottom: 4px;
      overflow-x: auto;
    }
    .payoff-bar-wrap { display: flex; flex-direction: column; align-items: center; flex: 1; min-width: 3px; }
    .payoff-bar { width: 100%; min-width: 2px; border-radius: 1px; }
    .bar-profit { background: #16a34a; }
    .bar-loss { background: #dc2626; }
    .payoff-label { margin-top: 4px; white-space: nowrap; }
    .text-xs { font-size: 0.7rem; }
    select {
      width: 100%; padding: 8px 12px; border: 1px solid var(--color-border);
      border-radius: var(--radius-md); background: var(--color-surface);
      color: var(--color-text); font-size: 0.9rem;
    }
    @media (max-width: 900px) {
      :host .flex.gap-2 { flex-direction: column; }
    }
  `]
})
export class OptionsBuilderComponent {
  underlying = 'NIFTY';
  spot = 24500;
  iv = 0.15;
  expiry = '';
  lotSize = 50;
  direction = 'bullish';
  confidence = 0.65;
  loading = false;

  result: StrategyRecommendation | null = null;
  payoffData: { spot: number; payoff: number }[] = [];
  maxPayoff = 1;
  labelInterval = 10;

  constructor(private optionsApi: OptionsApiService) {
    // Default expiry to next Thursday
    const now = new Date();
    const day = now.getDay();
    const daysUntilThursday = (4 - day + 7) % 7 || 7;
    const next = new Date(now);
    next.setDate(now.getDate() + daysUntilThursday);
    this.expiry = next.toISOString().split('T')[0];
  }

  private get payload() {
    return { underlying: this.underlying, spot: this.spot, expiry: this.expiry, iv: this.iv, lot_size: this.lotSize };
  }

  recommend(): void {
    this.loading = true;
    this.optionsApi.recommendStrategy({
      ...this.payload, direction: this.direction, confidence: this.confidence,
    }).subscribe({
      next: r => { this.handleResult(r); this.loading = false; },
      error: () => this.loading = false,
    });
  }

  buildCoveredCall(): void {
    this.optionsApi.buildCoveredCall(this.payload).subscribe({ next: r => this.handleResult(r) });
  }

  buildBullCallSpread(): void {
    this.optionsApi.buildBullCallSpread(this.payload).subscribe({ next: r => this.handleResult(r) });
  }

  buildIronCondor(): void {
    this.optionsApi.buildIronCondor(this.payload).subscribe({ next: r => this.handleResult(r) });
  }

  buildStraddle(): void {
    this.optionsApi.buildStraddle(this.payload).subscribe({ next: r => this.handleResult(r) });
  }

  private handleResult(r: StrategyRecommendation): void {
    this.result = r;
    if (r.legs?.length) {
      this.optionsApi.computePayoff(r.legs).subscribe({
        next: d => {
          this.payoffData = d;
          const vals = d.map(p => Math.abs(p.payoff));
          this.maxPayoff = Math.max(...vals, 1);
          this.labelInterval = Math.max(1, Math.floor(d.length / 8));
        },
        error: () => this.payoffData = []
      });
    }
  }

  getBarHeight(payoff: number): number {
    return Math.min(70, (Math.abs(payoff) / this.maxPayoff) * 70);
  }

  getBarMarginTop(payoff: number): number {
    return payoff >= 0 ? 70 - this.getBarHeight(payoff) : 70;
  }
}
