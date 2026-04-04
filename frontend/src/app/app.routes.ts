// App routes — Phase 1 shell layout with lazy loading and guards
import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { adminGuard } from './core/guards/admin.guard';
import { marketOpenGuard } from './core/guards/market-open.guard';
import { ShellComponent } from './shell/shell.component';

export const routes: Routes = [
  // ── Auth routes (outside shell) ──
  { path: 'auth/login', loadComponent: () => import('./pages/login.component').then(m => m.LoginComponent) },
  { path: 'auth/callback', loadComponent: () => import('./pages/callback.component').then(m => m.CallbackComponent) },

  // ── App shell (all authenticated routes) ──
  {
    path: '',
    component: ShellComponent,
    children: [
      // Market Overview (homepage)
      {
        path: '',
        loadComponent: () => import('./pages/market-overview.component').then(m => m.MarketOverviewComponent),
      },

      // Paper Trading
      {
        path: 'paper',
        loadComponent: () => import('./pages/paper-dashboard.component').then(m => m.PaperDashboardComponent),
        canActivate: [authGuard],
      },
      {
        path: 'account/:accountId',
        loadComponent: () => import('./pages/paper-account-detail.component').then(m => m.PaperAccountDetailComponent),
        canActivate: [authGuard],
      },

      // Market data
      {
        path: 'live',
        loadComponent: () => import('./pages/live-market.component').then(m => m.LiveMarketComponent),
        canActivate: [authGuard],
      },
      {
        path: 'chart',
        loadComponent: () => import('./pages/live-chart.component').then(m => m.LiveChartComponent),
        canActivate: [authGuard],
      },
      {
        path: 'chart/:symbol',
        loadComponent: () => import('./pages/live-chart.component').then(m => m.LiveChartComponent),
        canActivate: [authGuard],
      },

      // Predictions
      {
        path: 'signal-detail/:symbol',
        loadComponent: () => import('./pages/signal-detail.component').then(m => m.SignalDetailComponent),
        canActivate: [authGuard],
      },
      {
        path: 'signals',
        loadComponent: () => import('./pages/signal-explorer.component').then(m => m.SignalExplorerComponent),
        canActivate: [authGuard],
      },
      {
        path: 'signal-detail',
        loadComponent: () => import('./pages/signal-detail.component').then(m => m.SignalDetailComponent),
        canActivate: [authGuard],
      },

      // Trading
      {
        path: 'trading',
        loadComponent: () => import('./pages/trading.component').then(m => m.TradingComponent),
        canActivate: [authGuard, marketOpenGuard],
      },
      {
        path: 'options',
        loadComponent: () => import('./pages/options-builder.component').then(m => m.OptionsBuilderComponent),
        canActivate: [authGuard],
      },
      {
        path: 'execution',
        loadComponent: () => import('./pages/execution-quality.component').then(m => m.ExecutionQualityComponent),
        canActivate: [authGuard],
      },

      // Portfolio & Risk
      {
        path: 'portfolio',
        loadComponent: () => import('./pages/portfolio-dashboard.component').then(m => m.PortfolioDashboardComponent),
        canActivate: [authGuard],
      },
      {
        path: 'risk',
        loadComponent: () => import('./pages/risk-dashboard.component').then(m => m.RiskDashboardComponent),
        canActivate: [authGuard],
      },
      {
        path: 'regime',
        loadComponent: () => import('./pages/regime-panel.component').then(m => m.RegimePanelComponent),
        canActivate: [authGuard],
      },

      // Intelligence
      {
        path: 'news',
        loadComponent: () => import('./pages/news-feed.component').then(m => m.NewsFeedComponent),
        canActivate: [authGuard],
      },

      // Automation
      {
        path: 'bot',
        loadComponent: () => import('./pages/bot-panel.component').then(m => m.BotPanelComponent),
        canActivate: [authGuard],
      },
      {
        path: 'backtest',
        loadComponent: () => import('./pages/backtest.component').then(m => m.BacktestComponent),
        canActivate: [authGuard],
      },

      // System (admin)
      {
        path: 'system',
        loadComponent: () => import('./pages/system/system-shell.component').then(m => m.SystemShellComponent),
        canActivate: [authGuard, adminGuard],
        children: [
          { path: '', redirectTo: 'models', pathMatch: 'full' },
          { path: 'models', loadComponent: () => import('./pages/system/sys-models.component').then(m => m.SysModelsComponent) },
          { path: 'drift', loadComponent: () => import('./pages/system/sys-drift.component').then(m => m.SysDriftComponent) },
          { path: 'registry', loadComponent: () => import('./pages/system/sys-registry.component').then(m => m.SysRegistryComponent) },
          { path: 'canary', loadComponent: () => import('./pages/system/sys-canary.component').then(m => m.SysCanaryComponent) },
        ],
      },
    ],
  },

  // Fallback
  { path: '**', loadComponent: () => import('./pages/not-found.component').then(m => m.NotFoundComponent) },
];
