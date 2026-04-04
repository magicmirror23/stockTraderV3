export const environment = {
  production: true,
  // Route API traffic via Vercel rewrites to avoid direct gateway dependency.
  apiBaseUrl: '/api/v1',
  wsBaseUrl: 'wss://stocktrader-market-data-lyh3.onrender.com/api/v1',
  enableMocks: false,
  enableDebugTools: false,
  marketTimezone: 'Asia/Kolkata',
  defaultTheme: 'light' as 'light' | 'dark',
  cacheTtlMs: 15_000,
  wsReconnectMaxMs: 60_000,
};
