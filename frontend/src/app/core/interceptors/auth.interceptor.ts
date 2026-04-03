import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from '../../services/auth.service';

/**
 * Attaches Bearer token to all outgoing HTTP requests when available.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);

  if (auth.token) {
    const cloned = req.clone({
      setHeaders: { Authorization: `Bearer ${auth.token}` },
    });
    return next(cloned);
  }

  return next(req);
};
