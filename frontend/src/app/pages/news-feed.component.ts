// News & anomaly feed page component
import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { IntelligenceApiService, AnomalyAlert } from '../services/intelligence-api.service';

@Component({
  selector: 'app-news-feed',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1>News & Anomaly Feed</h1>

      <div class="flex gap-2" style="align-items: flex-start;">
        <!-- News Feed -->
        <div style="flex: 1.5;">
          <div class="card mb-2">
            <div class="flex justify-between items-center mb-1">
              <h2>Market News</h2>
              <div class="flex gap-1">
                <input [(ngModel)]="newsSymbol" placeholder="Symbol" style="width: 140px;" />
                <button class="btn-primary btn-sm" (click)="loadNews()" [disabled]="newsLoading">
                  {{ newsLoading ? 'Loading...' : 'Fetch' }}
                </button>
              </div>
            </div>

            <div *ngIf="!news" class="text-muted text-sm">Enter a symbol and click Fetch.</div>
            <div *ngFor="let article of news" class="news-card">
              <div class="flex justify-between items-center">
                <strong>{{ article.title }}</strong>
                <span class="badge" [ngClass]="{
                  'badge-success': article.sentiment?.label === 'positive',
                  'badge-danger': article.sentiment?.label === 'negative',
                  'badge-neutral': article.sentiment?.label === 'neutral'
                }">
                  {{ article.sentiment?.label || 'N/A' }}
                  <span *ngIf="article.sentiment?.score">({{ article.sentiment.score | number:'1.2-2' }})</span>
                </span>
              </div>
              <div class="text-sm text-muted mt-05">{{ article.summary || article.description }}</div>
              <div class="flex gap-05 mt-05 flex-wrap">
                <span *ngFor="let tag of article.sentiment?.event_tags" class="tag">{{ tag }}</span>
              </div>
              <div class="text-xs text-muted mt-05">{{ article.source }} · {{ article.published }}</div>
            </div>
          </div>

          <!-- Sentiment Analyzer -->
          <div class="card">
            <h2>Sentiment Analyzer</h2>
            <div class="form-group">
              <textarea [(ngModel)]="sentimentText" placeholder="Paste any text to analyze sentiment..." rows="3"></textarea>
            </div>
            <button class="btn-primary btn-sm" (click)="analyzeSentiment()" [disabled]="!sentimentText">Analyze</button>
            <div *ngIf="sentimentResult" class="mt-1">
              <div class="flex items-center gap-1">
                <span class="badge badge-lg" [ngClass]="{
                  'badge-success': sentimentResult.label === 'positive',
                  'badge-danger': sentimentResult.label === 'negative',
                  'badge-neutral': sentimentResult.label === 'neutral'
                }">{{ sentimentResult.label }}</span>
                <span class="text-mono">Score: {{ sentimentResult.score | number:'1.3-3' }}</span>
              </div>
              <div *ngIf="sentimentResult.event_tags?.length" class="flex gap-05 mt-05 flex-wrap">
                <span *ngFor="let tag of sentimentResult.event_tags" class="tag tag-event">{{ tag }}</span>
              </div>
              <div *ngIf="sentimentResult.keywords_found?.length" class="text-sm mt-05">
                Keywords: {{ sentimentResult.keywords_found.join(', ') }}
              </div>
            </div>
          </div>
        </div>

        <!-- Anomaly Alerts -->
        <div style="flex: 1;">
          <div class="card">
            <div class="flex justify-between items-center mb-1">
              <h2>Anomaly Alerts</h2>
              <button class="btn-primary btn-sm" (click)="loadAlerts()">Refresh</button>
            </div>
            <div *ngIf="!alerts" class="text-muted text-sm">Loading alerts...</div>
            <div *ngIf="alerts?.length === 0" class="text-muted text-sm">No anomalies detected.</div>
            <div *ngFor="let a of alerts" class="alert-card" [ngClass]="'alert-' + a.severity">
              <div class="flex justify-between items-center">
                <strong>{{ a.ticker }}</strong>
                <span class="badge" [ngClass]="{
                  'badge-danger': a.severity === 'high',
                  'badge-warning': a.severity === 'medium',
                  'badge-info': a.severity === 'low'
                }">{{ a.severity }}</span>
              </div>
              <div class="text-sm">{{ a.message }}</div>
              <div class="text-xs text-muted">Type: {{ a.type }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .news-card {
      padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-md);
      margin-bottom: 10px; transition: background var(--transition);
    }
    .news-card:hover { background: var(--color-surface-hover); }
    .alert-card {
      padding: 10px; border-radius: var(--radius-md); margin-bottom: 8px;
      border-left: 3px solid var(--color-border);
    }
    .alert-high { border-left-color: #dc2626; background: rgba(220,38,38,0.04); }
    .alert-medium { border-left-color: #f59e0b; background: rgba(245,158,11,0.04); }
    .alert-low { border-left-color: #6366f1; background: rgba(99,102,241,0.04); }
    .tag { padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; background: var(--color-border); }
    .tag-event { background: #fef3c7; color: #92400e; }
    .badge-success { background: #dcfce7; color: #166534; }
    .badge-danger { background: #fee2e2; color: #991b1b; }
    .badge-neutral { background: #f3f4f6; color: #4b5563; }
    .badge-warning { background: #fef3c7; color: #92400e; }
    .badge-info { background: #dbeafe; color: #1e40af; }
    .badge-lg { padding: 6px 16px; font-size: 1rem; }
    textarea { width: 100%; resize: vertical; }
    .mt-05 { margin-top: 0.375rem; }
    .gap-05 { gap: 0.375rem; }
    .text-xs { font-size: 0.75rem; }
    .flex-wrap { flex-wrap: wrap; }
    @media (max-width: 900px) {
      :host .flex.gap-2 { flex-direction: column; }
    }
  `]
})
export class NewsFeedComponent implements OnInit, OnDestroy {
  newsSymbol = 'RELIANCE';
  news: any[] | null = null;
  newsLoading = false;

  sentimentText = '';
  sentimentResult: any | null = null;

  alerts: any[] | null = null;

  private timer: any;

  constructor(private intelligenceApi: IntelligenceApiService) {}

  ngOnInit(): void {
    this.loadAlerts();
    this.timer = setInterval(() => this.loadAlerts(), 30_000);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  loadNews(): void {
    if (!this.newsSymbol) return;
    this.newsLoading = true;
    this.intelligenceApi.fetchNews(this.newsSymbol.trim()).subscribe({
      next: d => { this.news = d; this.newsLoading = false; },
      error: () => this.newsLoading = false
    });
  }

  analyzeSentiment(): void {
    if (!this.sentimentText) return;
    this.intelligenceApi.scoreSentiment(this.sentimentText).subscribe({
      next: d => this.sentimentResult = d,
      error: () => {}
    });
  }

  loadAlerts(): void {
    this.intelligenceApi.getRecentAlerts().subscribe({
      next: d => this.alerts = d,
      error: () => {}
    });
  }
}
