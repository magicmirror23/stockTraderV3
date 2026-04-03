// Price stream service
import { Injectable, NgZone } from '@angular/core';
import { Observable } from 'rxjs';
import { PriceTick } from '../core/models';

export { PriceTick };

@Injectable({ providedIn: 'root' })
export class PriceStreamService {
  constructor(private ngZone: NgZone) {}

  connect(symbol: string): Observable<PriceTick> {
    return new Observable<PriceTick>(subscriber => {
      const wsUrl = `ws://${window.location.host}/api/v1/stream/price/${encodeURIComponent(symbol)}`;
      const sseUrl = `/api/v1/stream/price/${encodeURIComponent(symbol)}`;

      try {
        const ws = new WebSocket(wsUrl);

        ws.onmessage = (event) => {
          this.ngZone.run(() => {
            subscriber.next(JSON.parse(event.data));
          });
        };

        ws.onerror = () => {
          ws.close();
          this.connectSSE(sseUrl, subscriber);
        };

        ws.onclose = () => {
          if (!subscriber.closed) {
            this.connectSSE(sseUrl, subscriber);
          }
        };

        return () => ws.close();
      } catch {
        return this.connectSSE(sseUrl, subscriber);
      }
    });
  }

  private connectSSE(url: string, subscriber: any): () => void {
    const source = new EventSource(url);
    source.onmessage = (event) => {
      this.ngZone.run(() => {
        subscriber.next(JSON.parse(event.data));
      });
    };
    source.onerror = () => {
      source.close();
      subscriber.complete();
    };
    return () => source.close();
  }
}
