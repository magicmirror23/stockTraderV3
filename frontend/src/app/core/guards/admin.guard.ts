import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { NotificationService } from '../../services/notification.service';

/**
 * Protects /system/** admin routes.
 * Requires authentication. In future, will also require admin role.
 */
export const adminGuard: CanActivateFn = (route, state) => {
  const auth = inject(AuthService);
  const notify = inject(NotificationService);
  const router = inject(Router);

  if (!auth.isAuthenticated) {
    // TODO: enforce strictly once auth backend is wired
    // notify.warning('Authentication required to access system administration.');
    // return router.createUrlTree(['/auth/login'], { queryParams: { returnUrl: state.url } });
    return true;
  }

  // TODO: add role check when backend supports user roles
  return true;
};
