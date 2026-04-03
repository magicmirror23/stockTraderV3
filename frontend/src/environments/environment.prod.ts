export const environment = {
  production: true,
  apiBaseUrl: '/api/v1',
  wsBaseUrl: `wss://${typeof window !== 'undefined' ? window.location.host : ''}/api/v1`,
  enableMocks: false,
  enableDebugTools: false,
  marketTimezone: 'Asia/Kolkata',
  defaultTheme: 'light' as 'light' | 'dark',
  cacheTtlMs: 15_000,
  wsReconnectMaxMs: 60_000,
};
