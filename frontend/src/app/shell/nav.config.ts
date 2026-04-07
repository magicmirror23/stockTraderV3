/** Navigation configuration for the sidebar and mobile menu. */

export interface NavItem {
  label: string;
  icon: string;            // bootstrap-icons class (without 'bi-' prefix)
  route: string;
  badge?: string;          // optional live badge key (resolved at runtime)
}

export interface NavGroup {
  heading: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    heading: 'Markets',
    items: [
      { label: 'Overview',     icon: 'grid-1x2-fill',   route: '/' },
      { label: 'Live Market',  icon: 'broadcast',       route: '/live' },
      { label: 'Charts',       icon: 'graph-up',        route: '/chart' },
      { label: 'News & Intel', icon: 'newspaper',       route: '/news' },
    ],
  },
  {
    heading: 'Trading',
    items: [
      { label: 'Trade',        icon: 'lightning-fill',   route: '/trading' },
      { label: 'Options',      icon: 'layers-fill',      route: '/options' },
      { label: 'Predictions',  icon: 'bullseye',         route: '/signals' },
      { label: 'Execution',    icon: 'speedometer2',     route: '/execution' },
    ],
  },
  {
    heading: 'Portfolio',
    items: [
      { label: 'Portfolio',    icon: 'pie-chart-fill',   route: '/portfolio' },
      { label: 'Risk',         icon: 'shield-exclamation', route: '/risk' },
      { label: 'Regime',       icon: 'thermometer-half', route: '/regime' },
    ],
  },
  {
    heading: 'Automation',
    items: [
      { label: 'Bot',          icon: 'robot',            route: '/bot' },
      { label: 'Backtest',     icon: 'clock-history',    route: '/backtest' },
      { label: 'Paper Trade',  icon: 'journal-text',     route: '/paper' },
    ],
  },
  {
    heading: 'Intraday',
    items: [
      { label: 'Intraday Models', icon: 'lightning-charge-fill', route: '/intraday/models' },
      { label: 'Options Signals', icon: 'bar-chart-steps',      route: '/intraday/options' },
      { label: 'Execution',       icon: 'crosshair',            route: '/intraday/execution' },
      { label: 'Supervisor',      icon: 'shield-check',         route: '/intraday/supervisor' },
    ],
  },
  {
    heading: 'System',
    items: [
      { label: 'Models',       icon: 'cpu',                  route: '/system/models' },
      { label: 'Drift',        icon: 'activity',             route: '/system/drift' },
      { label: 'Registry',     icon: 'archive',              route: '/system/registry' },
      { label: 'Canary',       icon: 'flag',                 route: '/system/canary' },
    ],
  },
];
