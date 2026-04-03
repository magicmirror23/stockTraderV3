export const environment = {
  production: false,
  apiBaseUrl: '/api/v1',
  wsBaseUrl: `ws://${typeof window !== 'undefined' ? window.location.host : 'localhost:8000'}/api/v1`,
  enableMocks: false,
  enableDebugTools: true,
  marketTimezone: 'Asia/Kolkata',
  defaultTheme: 'light' as 'light' | 'dark',
  cacheTtlMs: 30_000,
  wsReconnectMaxMs: 60_000,
};
