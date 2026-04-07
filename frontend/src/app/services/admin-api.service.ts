// Admin API service
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { ModelStatus, ModelReloadResponse, ModelVersion, DriftResult, CanaryStatus } from '../core/models';

export { ModelStatus, ModelReloadResponse, ModelVersion, DriftResult, CanaryStatus };

interface RegistryVersionsEnvelope {
  latest: string | null;
  versions: Array<ModelVersion & { timestamp?: string; metrics?: { test_accuracy?: number; classification_accuracy?: number; executed_trade_win_rate?: number } }>;
}

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private readonly base = environment.apiBaseUrl;

  constructor(private http: HttpClient) {}

  getModelStatus(): Observable<ModelStatus> {
    return this.http.get<ModelStatus>(`${this.base}/model/status`);
  }

  reloadModel(version?: string): Observable<ModelReloadResponse> {
    return this.http.post<ModelReloadResponse>(`${this.base}/model/reload`, { version: version || null });
  }

  triggerRetrain(): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${this.base}/retrain`, {});
  }

  getRegistryVersions(): Observable<ModelVersion[]> {
    return this.http.get<RegistryVersionsEnvelope>(`${this.base}/registry/versions`).pipe(
      map(res => (res.versions ?? []).map(version => ({
        version: version.version,
        created_at: version.created_at || version.timestamp || '',
        accuracy: version.accuracy ?? version.metrics?.classification_accuracy ?? version.metrics?.test_accuracy,
        executed_trade_win_rate: version.executed_trade_win_rate ?? version.metrics?.executed_trade_win_rate,
        status: version.version === res.latest ? 'active' : 'archived'
      })))
    );
  }

  getMLflowVersion(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(`${this.base}/registry/mlflow`);
  }

  checkDrift(): Observable<DriftResult> {
    return this.http.post<DriftResult>(`${this.base}/drift/check`, {});
  }

  getCanaryStatus(): Observable<CanaryStatus> {
    return this.http.get<CanaryStatus>(`${this.base}/canary/status`);
  }

  getMetrics(): Observable<string> {
    return this.http.get(`${this.base}/metrics`, { responseType: 'text' });
  }
}
