/**
 * LoggingService — Sends frontend logs to the backend for persistent file logging.
 *
 * Usage:
 *   constructor(private log: LoggingService) {}
 *   this.log.info('Order placed', 'TradePage');
 *   this.log.error('WebSocket disconnected', 'LiveStream');
 *
 * Logs are written to logs/frontend.log on the server.
 * Also mirrors to browser console in non-production builds.
 */
import { Injectable, isDevMode } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

@Injectable({ providedIn: 'root' })
export class LoggingService {
  private readonly endpoint = `${environment.apiBaseUrl}/log`;

  constructor(private http: HttpClient) {}

  debug(message: string, context?: string): void { this.send('debug', message, context); }
  info(message: string, context?: string): void  { this.send('info', message, context); }
  warn(message: string, context?: string): void  { this.send('warn', message, context); }
  error(message: string, context?: string): void { this.send('error', message, context); }

  private send(level: LogLevel, message: string, context?: string): void {
    // Mirror to browser console in dev mode
    if (isDevMode()) {
      const tag = context ? `[${context}]` : '';
      const consoleFn = level === 'error' ? console.error
        : level === 'warn' ? console.warn
        : level === 'debug' ? console.debug
        : console.log;
      consoleFn(`${tag} ${message}`);
    }

    // Fire-and-forget POST to backend
    this.http.post(this.endpoint, {
      level,
      message: message.substring(0, 2000),
      context: context?.substring(0, 500) ?? null,
      timestamp: new Date().toISOString(),
    }).subscribe({
      error: () => {}, // silently ignore logging failures
    });
  }
}
