// Prediction API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { PredictionResult, Greeks, OptionSignal } from '../core/models';

export { PredictionResult, Greeks, OptionSignal };

interface PredictEnvelope {
  ticker: string;
  horizon_days: number;
  predicted_price: number;
  confidence: number;
  model_version: string;
  timestamp: string;
  prediction: PredictionResult;
}

@Injectable({ providedIn: 'root' })
export class PredictionApiService {
  private readonly base = '/api/v1';

  constructor(private http: HttpClient) {}

  predict(ticker: string, horizon: string = '1d'): Observable<PredictionResult> {
    return this.http.post<PredictEnvelope>(`${this.base}/predict`, {
      ticker,
      horizon_days: this.toHorizonDays(horizon)
    }).pipe(
      map(res => res.prediction ?? {
        ticker: res.ticker,
        action: 'hold',
        confidence: res.confidence,
        expected_return: 0,
        model_version: res.model_version,
        timestamp: res.timestamp
      })
    );
  }

  predictOptions(underlying: string, strike: number, expiry: string, optionType: 'CE' | 'PE'): Observable<{ signal: OptionSignal }> {
    return this.http.post<{ signal: OptionSignal }>(`${this.base}/predict/options`, {
      underlying, strike, expiry, option_type: optionType,
    });
  }

  batchPredict(tickers: string[]): Observable<PredictionResult[]> {
    return this.http.post<{ predictions: PredictionResult[] }>(`${this.base}/batch_predict`, { tickers })
      .pipe(map(res => res.predictions));
  }

  modelStatus(): Observable<unknown> {
    return this.http.get(`${this.base}/model/status`);
  }

  private toHorizonDays(horizon: string): number {
    switch (horizon) {
      case '1d':
        return 1;
      case '5d':
      case '1w':
        return 5;
      default:
        return Number.parseInt(horizon, 10) || 5;
    }
  }
}
