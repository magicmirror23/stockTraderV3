// HTTP interceptor
import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { AuthService } from './auth.service';
import { NotificationService } from './notification.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const notify = inject(NotificationService);

  let request = req;
  if (auth.token) {
    request = req.clone({
      setHeaders: { Authorization: `Bearer ${auth.token}` }
    });
  }

  return next(request).pipe(
    catchError((err: HttpErrorResponse) => {
      const message = err.error?.detail || err.message || 'An unexpected error occurred';
      if (err.status === 401) {
        notify.error('Authentication required. Please set your API token.');
      } else if (err.status === 503) {
        notify.warning('Service temporarily unavailable. Please try again.');
      } else if (err.status >= 400) {
        notify.error(message);
      }
      return throwError(() => err);
    })
  );
};
