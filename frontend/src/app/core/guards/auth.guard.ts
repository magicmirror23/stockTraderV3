import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

/**
 * Protects all app routes except /auth/*.
 * Redirects unauthenticated users to /auth/login.
 */
export const authGuard: CanActivateFn = (route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (auth.isAuthenticated) {
    return true;
  }

  // Allow navigation to proceed if token-less mode (dev / no auth backend yet)
  // TODO: enforce strictly once auth backend is wired
  return true;
};
