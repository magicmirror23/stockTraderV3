import { Injectable, NgZone } from '@angular/core';
import { Observable, Subject, BehaviorSubject, timer } from 'rxjs';
import { environment } from '../../../environments/environment';

export type WsConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface WsMessage {
  type: string;
  data: any;
}

/**
 * Reusable WebSocket manager with exponential-backoff reconnection.
 *
 * Features:
 *  - Auto-reconnect with jitter (1s → 2s → 4s … capped at wsReconnectMaxMs)
 *  - Falls back to SSE when WebSocket construction fails
 *  - NgZone-aware message delivery
 *  - Observable-based message stream
 *
 * Usage:
 *   const ws = websocketService.connect('/stream/multi');
 *   ws.messages$.subscribe(msg => ...);
 *   ws.send({ action: 'subscribe', symbols: ['RELIANCE'] });
 *   ws.disconnect();
 */
@Injectable({ providedIn: 'root' })
export class WebsocketService {
  constructor(private ngZone: NgZone) {}

  /**
   * Create a managed WebSocket connection to the given path.
   * @param path  Relative path appended to environment.wsBaseUrl (e.g. '/stream/multi')
   * @param sseUrl Optional SSE fallback URL (absolute or relative)
   */
  connect(path: string, sseUrl?: string): ManagedConnection {
    const wsUrl = this.normalizeWsUrl(`${environment.wsBaseUrl}${path}`);
    return new ManagedConnection(
      wsUrl,
      sseUrl ?? `${environment.apiBaseUrl}${path}`,
      this.ngZone,
    );
  }

  private normalizeWsUrl(url: string): string {
    if (typeof window !== 'undefined' && window.location.protocol === 'https:' && url.startsWith('ws://')) {
      return `wss://${url.slice(5)}`;
    }
    return url;
  }
}

export class ManagedConnection {
  private ws: WebSocket | null = null;
  private sse: EventSource | null = null;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  private readonly maxBackoffMs = environment.wsReconnectMaxMs;
  private readonly baseDelayMs = 1000;

  private readonly _messages = new Subject<any>();
  private readonly _state = new BehaviorSubject<WsConnectionState>('disconnected');

  /** Emits every parsed JSON message from the server. */
  readonly messages$ = this._messages.asObservable();
  /** Current connection state. */
  readonly state$ = this._state.asObservable();

  get state(): WsConnectionState { return this._state.value; }

  constructor(
    private wsUrl: string,
    private sseUrl: string,
    private ngZone: NgZone,
  ) {
    this.openWebSocket();
  }

  /** Send a JSON-serialisable message to the server. */
  send(data: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  /** Close the connection permanently (no reconnect). */
  disconnect(): void {
    this.intentionalClose = true;
    this.clearReconnect();
    this.ws?.close();
    this.sse?.close();
    this.ws = null;
    this.sse = null;
    this._state.next('disconnected');
    this._messages.complete();
  }

  // ----- internals -----

  private openWebSocket(): void {
    this._state.next('connecting');

    try {
      this.ws = new WebSocket(this.wsUrl);
    } catch {
      this.fallbackToSSE();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempt = 0;
      this._state.next('connected');
    };

    this.ws.onmessage = (event) => {
      this.ngZone.run(() => {
        try {
          this._messages.next(JSON.parse(event.data));
        } catch {
          this._messages.next(event.data);
        }
      });
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };

    this.ws.onclose = () => {
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };
  }

  private fallbackToSSE(): void {
    this._state.next('connecting');
    this.sse = new EventSource(this.sseUrl);

    this.sse.onopen = () => {
      this.reconnectAttempt = 0;
      this._state.next('connected');
    };

    this.sse.onmessage = (event) => {
      this.ngZone.run(() => {
        try {
          this._messages.next(JSON.parse(event.data));
        } catch {
          this._messages.next(event.data);
        }
      });
    };

    this.sse.onerror = () => {
      this.sse?.close();
      this.sse = null;
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect(): void {
    this._state.next('reconnecting');

    // Exponential backoff with jitter
    const delay = Math.min(
      this.baseDelayMs * Math.pow(2, this.reconnectAttempt) + Math.random() * 500,
      this.maxBackoffMs,
    );
    this.reconnectAttempt++;

    this.reconnectTimer = setTimeout(() => {
      this.openWebSocket();
    }, delay);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
