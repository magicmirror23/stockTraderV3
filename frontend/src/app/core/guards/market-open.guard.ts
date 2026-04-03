import { inject } from '@angular/core';
import { CanActivateFn } from '@angular/router';
import { map, catchError, of } from 'rxjs';
import { MarketApiService } from '../../services/market-api.service';
import { NotificationService } from '../../services/notification.service';

/**
 * Warns (does not block) when navigating to /trading while market is closed.
 * Configurable: set `blockWhenClosed = true` to hard-block instead.
 */
const BLOCK_WHEN_CLOSED = false;

export const marketOpenGuard: CanActivateFn = (route, state) => {
  const market = inject(MarketApiService);
  const notify = inject(NotificationService);

  return market.getMarketStatus().pipe(
    map(status => {
      const openPhases = ['open', 'pre_open'];
      if (openPhases.includes(status.phase)) {
        return true;
      }

      const msg = `Market is ${status.phase}. ${status.message}`;
      if (BLOCK_WHEN_CLOSED) {
        notify.warning(msg + ' Trading is disabled.');
        return false;
      }

      notify.info(msg + ' Orders will queue for next session.');
      return true;
    }),
    catchError(() => {
      // If we can't reach market status API, allow through with warning
      notify.warning('Unable to verify market status.');
      return of(true);
    }),
  );
};
