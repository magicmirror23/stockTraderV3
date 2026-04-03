import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';

interface CacheEntry<T> {
  value: T;
  expiresAt: number;
}

/**
 * In-memory TTL cache for GET responses and computed values.
 *
 * Usage:
 *   cache.set('key', data);           // uses default TTL
 *   cache.set('key', data, 10_000);   // 10s TTL
 *   const hit = cache.get<MyType>('key');
 *   cache.invalidate('key');
 *   cache.invalidatePattern('/api/v1/risk');
 */
@Injectable({ providedIn: 'root' })
export class CacheService {
  private readonly store = new Map<string, CacheEntry<any>>();
  private readonly maxEntries = 512;
  private readonly defaultTtl = environment.cacheTtlMs;

  /** Retrieve cached value or null if expired/missing. */
  get<T>(key: string): T | null {
    const entry = this.store.get(key);
    if (!entry) return null;

    if (Date.now() > entry.expiresAt) {
      this.store.delete(key);
      return null;
    }

    return entry.value as T;
  }

  /** Store a value with optional custom TTL (ms). */
  set<T>(key: string, value: T, ttlMs?: number): void {
    // Evict oldest entries if at capacity
    if (this.store.size >= this.maxEntries) {
      const firstKey = this.store.keys().next().value;
      if (firstKey !== undefined) {
        this.store.delete(firstKey);
      }
    }

    this.store.set(key, {
      value,
      expiresAt: Date.now() + (ttlMs ?? this.defaultTtl),
    });
  }

  /** Remove a specific cache entry. */
  invalidate(key: string): void {
    this.store.delete(key);
  }

  /** Remove all entries whose key starts with the given prefix. */
  invalidatePattern(prefix: string): void {
    for (const key of this.store.keys()) {
      if (key.startsWith(prefix)) {
        this.store.delete(key);
      }
    }
  }

  /** Remove all cache entries. */
  clear(): void {
    this.store.clear();
  }

  /** Current number of cached entries (for diagnostics). */
  get size(): number {
    return this.store.size;
  }
}
