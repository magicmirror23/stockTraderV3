// News, sentiment & anomaly detection API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { SentimentResult, AnomalyAlert } from '../core/models';

export { SentimentResult, AnomalyAlert };

@Injectable({ providedIn: 'root' })
export class IntelligenceApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  scoreSentiment(text: string): Observable<SentimentResult> {
    return this.http.post<SentimentResult>(`${this.base}/sentiment/score`, { text });
  }

  fetchNews(symbol: string, limit = 10): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/news/${symbol}`, { params: { limit } });
  }

  checkAnomalies(payload: any): Observable<AnomalyAlert[]> {
    return this.http.post<AnomalyAlert[]>(`${this.base}/anomaly/check`, payload);
  }

  getRecentAlerts(limit = 20): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/anomaly/alerts`, { params: { limit } });
  }
}
