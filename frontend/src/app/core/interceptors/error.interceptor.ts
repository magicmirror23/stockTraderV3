import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NotificationService } from '../../services/notification.service';

/**
 * Centralised API error handling.
 * Maps HTTP error codes to user-facing toast notifications
 * and re-throws so component-level handlers still receive the error.
 */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const notify = inject(NotificationService);

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status === 0) {
        notify.error('Network error — cannot reach the server.');
      } else if (err.status === 401) {
        notify.error('Authentication required. Please set your API token.');
      } else if (err.status === 403) {
        notify.error('Access denied.');
      } else if (err.status === 404) {
        // Silently ignore 404s for optional endpoints (e.g. feed-status)
        // Components handle 404 at their level
      } else if (err.status === 429) {
        notify.warning('Rate limited — please wait before retrying.');
      } else if (err.status === 503) {
        notify.warning('Service temporarily unavailable. Please try again.');
      } else if (err.status >= 500) {
        notify.error('Server error. Please try again later.');
      } else if (err.status >= 400) {
        const detail = err.error?.detail || err.error?.message || err.message || 'Request failed.';
        notify.error(detail);
      }

      return throwError(() => err);
    }),
  );
};
