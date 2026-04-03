import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { of, tap } from 'rxjs';
import { CacheService } from '../services/cache.service';

/**
 * Optional HTTP-level cache interceptor.
 * Caches GET responses using CacheService's in-memory TTL store.
 * Mutations (POST/PUT/DELETE) invalidate related cache entries.
 *
 * Register AFTER auth + error interceptors in the provider chain.
 */
export const cacheInterceptor: HttpInterceptorFn = (req, next) => {
  const cache = inject(CacheService);

  // Only cache GET requests
  if (req.method !== 'GET') {
    // Invalidate cache for the same URL on mutations
    if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(req.method)) {
      cache.invalidate(req.url);
    }
    return next(req);
  }

  // Skip cache for streaming / websocket URLs
  if (req.url.includes('/stream/')) {
    return next(req);
  }

  // Check cache
  const cached = cache.get<HttpResponse<unknown>>(req.url);
  if (cached) {
    return of(cached.clone());
  }

  return next(req).pipe(
    tap(event => {
      if (event instanceof HttpResponse && event.status === 200) {
        cache.set(req.url, event.clone());
      }
    }),
  );
};
