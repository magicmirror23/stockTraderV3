# Frontend Rebuild Plan — Commercial-Grade Trading Platform UI

> Bootstrap 5 · Angular 18 Standalone · Modular Architecture

---

## PART 1 — CURRENT ISSUES LIST

### Architecture Issues
| # | Issue | Severity |
|---|-------|----------|
| A1 | **No lazy loading** — all 16 pages eagerly loaded, bloating initial bundle | High |
| A2 | **No route guards** — `/admin`, `/trading`, `/bot` accessible without auth | High |
| A3 | **No shared module / barrel exports** — every component re-imports CommonModule, FormsModule | Medium |
| A4 | **40+ interfaces scattered inline** across 17 service files — no models folder | Medium |
| A5 | **No environment files** — no `environment.ts` / `environment.prod.ts` | Medium |
| A6 | **No error boundary / global error handler** beyond interceptor toasts | Medium |
| A7 | **@swimlane/ngx-charts** in package.json but **never used** — dead dependency | Low |

### Styling Issues
| # | Issue | Severity |
|---|-------|----------|
| S1 | **No Bootstrap** — hand-rolled CSS with custom utility classes (.grid-2, .flex, .gap-1) that duplicate Bootstrap's grid/flex system | High |
| S2 | **All styles inline** in component .ts files — no external .component.css files, defeating Angular's style encapsulation | High |
| S3 | **Global styles.css** redefines `.btn`, `.card`, `.badge`, `.table` — will conflict with Bootstrap class names | High |
| S4 | **No Sass/SCSS** — vanilla CSS only, no variables nesting or mixins | Medium |
| S5 | **Inconsistent color usage** — components hardcode hex values (#16a34a, #dc2626) instead of using CSS custom properties | Medium |
| S6 | **90 lines of inline CSS** in app.component.ts for the navbar alone | Medium |
| S7 | **Responsive breakpoints** are ad-hoc — single `@media (max-width: 768px)` rule, no tablet/desktop/xl tiers | Medium |

### UX / Layout Issues
| # | Issue | Severity |
|---|-------|----------|
| U1 | **Paper Dashboard as homepage** — a trading platform should land on Market Overview or Portfolio, not paper trading accounts | High |
| U2 | **14 nav links in flat topnav** — cluttered, no grouping/dropdowns, overwhelms users | High |
| U3 | **No persistent sidebar** — trading platforms use left sidebar for navigation, freeing horizontal space for data | High |
| U4 | **live-market.component** is 200+ lines of template — does watchlist, indices, categories, ticker tape all in one | High |
| U5 | **admin.component** is 180+ lines — combines model management, drift monitoring, registry, and canary in one page with tabs | Medium |
| U6 | **No loading skeletons** — pages show nothing until API responds, then pop in | Medium |
| U7 | **No empty states** — pages with no data show blank areas | Medium |
| U8 | **No keyboard shortcuts** — essential for trading platforms (quick order, symbol search) | Medium |
| U9 | **signal-detail and signal-explorer** are separate pages but logically one workflow | Low |
| U10 | **No persistent watchlist panel** — traders need watchlist visible across all views | High |
| U11 | **No symbol search / command palette** — no way to quickly jump to a ticker | High |

### Component Quality Issues
| # | Issue | Severity |
|---|-------|----------|
| C1 | **Custom SVG charts everywhere** — equity-chart, live-price-chart, sparkline all hand-roll SVG instead of using a proper charting library | High |
| C2 | **order-intent-form has no validation** — can submit empty/invalid orders | High |
| C3 | **simulation-summary-card silences errors** — `error: () => {}` swallows failures | Medium |
| C4 | **No reusable stat-card, metric-card, data-table** — each page rebuilds its own stats/tables | Medium |
| C5 | **equity-chart lacks interactivity** — no tooltip, zoom, crosshair, or time range selector | Medium |
| C6 | **live-price-chart lacks candlestick view** — only renders line chart | Medium |

### Service Issues
| # | Issue | Severity |
|---|-------|----------|
| V1 | **model/status** duplicated in prediction-api.service and admin-api.service | Low |
| V2 | **No caching layer** — every page re-fetches on navigation | Medium |
| V3 | **No retry/backoff** on API calls — only interceptor toasts on failure | Medium |
| V4 | **market-api.service** bundles market status + bot control + account profile — should be split | Medium |
| V5 | **No WebSocket reconnection strategy** in live-stream.service beyond SSE fallback | Medium |

---

## PART 2 — COMPONENTS/PAGES TO REMOVE

| File | Reason |
|------|--------|
| `pages/signal-detail.component.ts` | Merge into signal-explorer as expandable row or slide-out panel |
| `pages/execution-quality.component.ts` | Low-value standalone page. Merge into Admin → System tab |
| `pages/regime-panel.component.ts` | Merge into Market Overview as a regime indicator widget |
| `components/simulation-summary-card.component.ts` | Replace with generic `<app-metric-card>` component |
| `@swimlane/ngx-charts` (package.json) | Remove — unused dependency |
| Entire `styles.css` utility framework | Replace with Bootstrap 5 utilities |

---

## PART 3 — COMPONENTS/PAGES TO REBUILD

### Pages — Full Rebuild

| Current | New | Why |
|---------|-----|-----|
| `paper-dashboard` (homepage) | **Market Overview** | Homepage must show market status, indices, top movers, watchlist, news — not paper accounts |
| `live-market` (200+ line monolith) | **Market Overview** + **Watchlist Sidebar** | Split into composed widgets: indices bar, watchlist panel, sector heatmap |
| `live-chart` | **Chart View** | Rebuild with TradingView Lightweight Charts or similar — candlestick, indicators, drawing tools |
| `trading` | **Order Entry** | Rebuild as a persistent side panel or modal — not a full page. Include validation, real-time price, margin check |
| `signal-explorer` + `signal-detail` | **Predictions** | Single page with signal table + expandable detail row. Batch predict inline |
| `options-builder` | **Options** | Real options chain display, payoff diagram, strategy builder with legs editor |
| `bot-panel` | **Bot Control** | Rebuild with better state machine UI, run history, P&L tracking |
| `admin` | **System** | Rebuild as proper admin section with sub-routes: /system/models, /system/drift, /system/registry, /system/canary |
| `portfolio-dashboard` | **Portfolio** | Rebuild with positions table, daily P&L chart, sector/strategy breakdown, holdings detail |
| `risk-dashboard` | **Risk** | Rebuild with risk gauges, exposure treemap, Greeks summary, alert history |
| `news-feed` | **News & Events** | Rebuild with streaming news cards, sentiment badges, event calendar |
| `backtest` | **Backtest** | Keep structure, rebuild UI with Bootstrap forms, results cards, equity chart |

### Components — Full Rebuild

| Current | New | Why |
|---------|-----|-----|
| `equity-chart` | `<app-chart>` | Unified chart component wrapping a proper library (Lightweight Charts) |
| `live-price-chart` | Absorbed into `<app-chart>` | One chart component, multiple modes (line, candle, area) |
| `sparkline` | `<app-sparkline>` | Keep concept, rebuild with consistent sizing and Bootstrap color tokens |
| `ticker-tape` | `<app-ticker-tape>` | Keep, restyle to Bootstrap |
| `order-intent-form` | `<app-order-form>` | Rebuild with reactive forms, validation, real-time pricing |

---

## PART 4 — NEW ROUTE STRUCTURE

```
/                              → Market Overview (default)
/portfolio                     → Portfolio Dashboard
/portfolio/positions           → Positions Detail
/portfolio/holdings            → Holdings Detail
/chart/:symbol                 → Full Chart View
/trading                       → Trading Terminal (chart + order entry + book)
/options                       → Options Chain + Strategy Builder
/options/payoff                → Payoff Diagram
/predictions                   → Signal Explorer (with inline detail)
/predictions/batch             → Batch Predictions
/backtest                      → Backtest Runner
/backtest/:jobId               → Backtest Results
/bot                           → Bot Control Panel
/bot/history                   → Bot Trade History
/risk                          → Risk Dashboard
/news                          → News & Events Feed
/paper                         → Paper Trading Accounts
/paper/:accountId              → Paper Account Detail
/system                        → System Admin (lazy loaded, guarded)
/system/models                 → Model Management
/system/drift                  → Drift Monitoring
/system/registry               → Model Registry
/system/canary                 → Canary Deployment
/auth/login                    → Login Page
/auth/callback                 → OAuth Callback
```

**Lazy-loaded feature modules:**
- `SystemModule` → `/system/**`
- `PaperModule` → `/paper/**`
- `BacktestModule` → `/backtest/**`
- `BotModule` → `/bot/**`

**Route guards:**
- `authGuard` → All routes except `/auth/*`
- `adminGuard` → `/system/**`
- `marketOpenGuard` → `/trading` (warn if market closed)

---

## PART 5 — NEW SHARED COMPONENT SYSTEM

### Layout Components (Bootstrap 5)
```
layout/
├── shell.component.ts              # App shell: sidebar + topbar + content
├── sidebar.component.ts            # Collapsible left nav with icon groups
├── topbar.component.ts             # Symbol search + notifications + account menu
├── breadcrumb.component.ts         # Route-driven breadcrumb
└── footer.component.ts             # Status bar: market phase, connection, clock
```

### Core UI Components
```
shared/components/
├── stat-card.component.ts           # Reusable metric card (label, value, change%, icon)
├── data-table.component.ts          # Sortable/filterable/paginated table
├── chart.component.ts               # Unified chart wrapper (line, candle, area)
├── sparkline.component.ts           # Mini inline chart
├── ticker-tape.component.ts         # Scrolling ticker bar
├── loading-skeleton.component.ts    # Skeleton placeholder for loading states
├── empty-state.component.ts         # "No data" placeholder with action button
├── confirm-dialog.component.ts      # Modal confirmation dialog
├── badge.component.ts               # Status/action badge (buy, sell, hold, etc.)
├── price-display.component.ts       # Formatted price with color + change arrow
├── pnl-display.component.ts         # P&L with color coding and percentage
├── mini-watchlist.component.ts      # Compact watchlist panel for sidebar/overlay
├── order-form.component.ts          # Reactive order entry form with validation
├── symbol-search.component.ts       # Command-palette style ticker search
├── notification-toast.component.ts  # Toast notification container
├── greeks-display.component.ts      # Options Greeks row/card
└── risk-gauge.component.ts          # Circular/linear gauge for risk metrics
```

### Directives & Pipes
```
shared/
├── directives/
│   ├── click-outside.directive.ts    # Close dropdowns on outside click
│   ├── autofocus.directive.ts        # Auto-focus input on render
│   └── shortcut-key.directive.ts     # Bind keyboard shortcuts
├── pipes/
│   ├── currency-inr.pipe.ts          # ₹1,23,456.78 Indian format
│   ├── compact-number.pipe.ts        # 1.2Cr, 45.3L, 12.5K
│   ├── relative-time.pipe.ts         # "2m ago", "1h ago"
│   ├── change-color.pipe.ts          # Returns 'text-success'/'text-danger' class
│   └── ticker-format.pipe.ts         # NIFTY 50 → NIFTY50, normalize symbols
```

---

## PART 6 — SHARED SERVICES

```
core/services/
├── auth.service.ts                  # Login, token refresh, session, logout
├── market-data.service.ts           # Market status, indices, sectors (REST)
├── price-stream.service.ts          # WebSocket/SSE price streaming + reconnect
├── order.service.ts                 # Trade intents, execution, order history
├── position.service.ts              # Open positions, P&L, close position
├── holdings.service.ts              # Long-term holdings, cost basis, returns
├── options.service.ts               # Chain data, strategy builder, payoff calc
├── prediction.service.ts            # Signals, batch predict, model status
├── bot.service.ts                   # Bot lifecycle, config, history, consent
├── portfolio.service.ts             # Portfolio metrics, allocation, daily summary
├── risk.service.ts                  # Risk status, exposure, limits, Greeks
├── news.service.ts                  # News feed, sentiment, anomaly alerts
├── notification.service.ts          # Toast + push notifications
├── system.service.ts                # Admin: model registry, drift, canary, retrain
├── backtest.service.ts              # Backtest submit, poll, results
├── cache.service.ts                 # Client-side response cache with TTL
└── websocket.service.ts             # Base WebSocket manager with reconnect logic
```

**Key changes from current services:**
- `market-api.service` → split into `market-data.service` + `bot.service`
- `paper-api.service` → kept as-is (isolated feature module)
- `live-stream.service` + `price-stream.service` → unified `price-stream.service` + shared `websocket.service`
- `strategy-api.service` → absorbed into `prediction.service` (regime) + `options.service` (strategy)
- `intelligence-api.service` → renamed to `news.service`
- `execution-api.service` → merged into `order.service`
- `admin-api.service` → renamed to `system.service`
- New: `position.service`, `holdings.service`, `cache.service`, `websocket.service`

---

## PART 7 — NEW FOLDER STRUCTURE

```
frontend/src/
├── index.html
├── main.ts
├── styles.scss                         # Bootstrap 5 imports + theme overrides only
├── _variables.scss                     # Bootstrap variable overrides (colors, fonts, spacing)
├── environments/
│   ├── environment.ts                  # API base URL, WS URL, feature flags
│   └── environment.prod.ts             # Production config
├── assets/
│   ├── icons/                          # SVG icon sprites
│   └── images/                         # Logo, favicons
├── app/
│   ├── app.component.ts
│   ├── app.config.ts
│   ├── app.routes.ts
│   │
│   ├── core/                           # Singleton services, guards, interceptors
│   │   ├── services/                   # All 17 services listed in Part 6
│   │   ├── guards/
│   │   │   ├── auth.guard.ts
│   │   │   ├── admin.guard.ts
│   │   │   └── market-open.guard.ts
│   │   ├── interceptors/
│   │   │   ├── auth.interceptor.ts
│   │   │   ├── error.interceptor.ts
│   │   │   └── cache.interceptor.ts
│   │   └── models/                     # ALL TypeScript interfaces/types
│   │       ├── market.model.ts         # MarketStatus, LiveTick, WatchlistItem
│   │       ├── order.model.ts          # TradeIntent, Execution, OrderBook
│   │       ├── position.model.ts       # Position, Holding
│   │       ├── prediction.model.ts     # PredictionResult, OptionSignal, Greeks
│   │       ├── portfolio.model.ts      # PortfolioMetrics, Allocation
│   │       ├── risk.model.ts           # RiskStatus, Exposure, RiskApproval
│   │       ├── options.model.ts        # OptionLeg, StrategyRecommendation, Chain
│   │       ├── backtest.model.ts       # BacktestResult, BacktestTrade
│   │       ├── bot.model.ts            # BotStatus, BotConfig
│   │       ├── news.model.ts           # Article, SentimentResult, AnomalyAlert
│   │       ├── system.model.ts         # ModelVersion, DriftResult, CanaryStatus
│   │       └── auth.model.ts           # User, Session, Token
│   │
│   ├── shared/                         # Reusable non-page components
│   │   ├── components/                 # All 17+ components from Part 5
│   │   ├── directives/
│   │   ├── pipes/
│   │   └── index.ts                    # Barrel export
│   │
│   ├── layout/                         # Shell, sidebar, topbar, footer
│   │   ├── shell.component.ts
│   │   ├── sidebar.component.ts
│   │   ├── topbar.component.ts
│   │   └── footer.component.ts
│   │
│   └── features/                       # Feature page modules
│       ├── market-overview/            # / — homepage
│       │   ├── market-overview.component.ts
│       │   ├── market-overview.component.html
│       │   ├── market-overview.component.scss
│       │   ├── widgets/
│       │   │   ├── indices-bar.component.ts
│       │   │   ├── top-movers.component.ts
│       │   │   ├── sector-heatmap.component.ts
│       │   │   └── market-regime.component.ts
│       │   └── market-overview.routes.ts
│       │
│       ├── portfolio/                  # /portfolio
│       │   ├── portfolio.component.ts
│       │   ├── portfolio.component.html
│       │   ├── portfolio.component.scss
│       │   ├── pages/
│       │   │   ├── positions.component.ts
│       │   │   └── holdings.component.ts
│       │   └── portfolio.routes.ts
│       │
│       ├── chart/                      # /chart/:symbol
│       │   ├── chart-view.component.ts
│       │   ├── chart-view.component.html
│       │   └── chart-view.component.scss
│       │
│       ├── trading/                    # /trading
│       │   ├── trading-terminal.component.ts
│       │   ├── trading-terminal.component.html
│       │   ├── trading-terminal.component.scss
│       │   └── widgets/
│       │       ├── order-book.component.ts
│       │       ├── order-entry.component.ts
│       │       └── trade-history.component.ts
│       │
│       ├── options/                    # /options
│       │   ├── options.component.ts
│       │   ├── options.component.html
│       │   ├── options.component.scss
│       │   └── widgets/
│       │       ├── option-chain.component.ts
│       │       ├── strategy-builder.component.ts
│       │       └── payoff-diagram.component.ts
│       │
│       ├── predictions/                # /predictions
│       │   ├── predictions.component.ts
│       │   ├── predictions.component.html
│       │   └── predictions.component.scss
│       │
│       ├── backtest/                   # /backtest (lazy loaded)
│       │   ├── backtest.component.ts
│       │   ├── backtest.component.html
│       │   ├── backtest.component.scss
│       │   ├── backtest-results.component.ts
│       │   └── backtest.routes.ts
│       │
│       ├── bot/                        # /bot (lazy loaded)
│       │   ├── bot-panel.component.ts
│       │   ├── bot-panel.component.html
│       │   ├── bot-panel.component.scss
│       │   ├── bot-history.component.ts
│       │   └── bot.routes.ts
│       │
│       ├── risk/                       # /risk
│       │   ├── risk-dashboard.component.ts
│       │   ├── risk-dashboard.component.html
│       │   └── risk-dashboard.component.scss
│       │
│       ├── news/                       # /news
│       │   ├── news-feed.component.ts
│       │   ├── news-feed.component.html
│       │   └── news-feed.component.scss
│       │
│       ├── paper/                      # /paper (lazy loaded)
│       │   ├── paper-dashboard.component.ts
│       │   ├── paper-detail.component.ts
│       │   └── paper.routes.ts
│       │
│       ├── system/                     # /system (lazy loaded, admin guard)
│       │   ├── system.component.ts
│       │   ├── pages/
│       │   │   ├── models.component.ts
│       │   │   ├── drift.component.ts
│       │   │   ├── registry.component.ts
│       │   │   └── canary.component.ts
│       │   └── system.routes.ts
│       │
│       └── auth/                       # /auth
│           ├── login.component.ts
│           └── callback.component.ts
```

---

## PART 8 — IMPLEMENTATION ORDER

### Phase 0 — Foundation (do first)
| Step | Task | Est. Files |
|------|------|-----------|
| 0.1 | Install Bootstrap 5 + bootstrap-icons, remove ngx-charts, add `lightweight-charts` | package.json |
| 0.2 | Convert styles.css → styles.scss with Bootstrap imports + `_variables.scss` | 2 files |
| 0.3 | Create `environments/` with environment.ts + environment.prod.ts | 2 files |
| 0.4 | Create `core/models/` — extract all 40+ interfaces from services into 12 model files | 12 files |
| 0.5 | Create `core/guards/` — auth.guard.ts, admin.guard.ts, market-open.guard.ts | 3 files |
| 0.6 | Split http.interceptor.ts → auth.interceptor.ts + error.interceptor.ts | 2 files |
| 0.7 | Create `core/services/websocket.service.ts` — shared reconnect logic | 1 file |
| 0.8 | Create `core/services/cache.service.ts` — client-side TTL cache | 1 file |

### Phase 1 — Layout Shell
| Step | Task | Est. Files |
|------|------|-----------|
| 1.1 | Build `layout/shell.component` — sidebar + topbar + router-outlet | 3 files |
| 1.2 | Build `layout/sidebar.component` — collapsible nav with icon groups | 3 files |
| 1.3 | Build `layout/topbar.component` — symbol search + notifications + user menu | 3 files |
| 1.4 | Build `layout/footer.component` — market status bar, connection indicator, IST clock | 3 files |
| 1.5 | Rebuild `app.component` to use shell, remove inline 140-line template | 1 file |
| 1.6 | Update `app.routes.ts` with new route map + lazy loading + guards | 1 file |

### Phase 2 — Shared Components
| Step | Task | Est. Files |
|------|------|-----------|
| 2.1 | `shared/components/stat-card` — metric card with label, value, change, icon | 3 files |
| 2.2 | `shared/components/data-table` — sortable, filterable, paginated | 3 files |
| 2.3 | `shared/components/chart` — Lightweight Charts wrapper (candle, line, area) | 3 files |
| 2.4 | `shared/components/sparkline` — rebuild with Bootstrap colors | 1 file |
| 2.5 | `shared/components/ticker-tape` — restyle to Bootstrap | 1 file |
| 2.6 | `shared/components/loading-skeleton` + `empty-state` | 2 files |
| 2.7 | `shared/components/price-display` + `pnl-display` + `badge` | 3 files |
| 2.8 | `shared/components/symbol-search` — command palette overlay | 3 files |
| 2.9 | `shared/components/order-form` — reactive form with validation | 3 files |
| 2.10 | `shared/components/greeks-display` + `risk-gauge` | 2 files |
| 2.11 | `shared/pipes/` — currency-inr, compact-number, relative-time, change-color | 4 files |
| 2.12 | `shared/directives/` — click-outside, autofocus, shortcut-key | 3 files |

### Phase 3 — Core Pages (build in this order)
| Step | Task | Replaces |
|------|------|----------|
| 3.1 | **Market Overview** (`/`) — indices bar, top movers, regime widget, sector heatmap | paper-dashboard, live-market, regime-panel |
| 3.2 | **Portfolio** (`/portfolio`) — positions, holdings, daily P&L chart, breakdown | portfolio-dashboard |
| 3.3 | **Chart View** (`/chart/:symbol`) — candlestick chart with indicators | live-chart |
| 3.4 | **Trading Terminal** (`/trading`) — chart + order entry + order book + history | trading |
| 3.5 | **Predictions** (`/predictions`) — signal table + expandable detail + batch | signal-explorer, signal-detail |
| 3.6 | **Options** (`/options`) — chain, strategy builder, payoff diagram | options-builder |
| 3.7 | **Risk** (`/risk`) — gauges, exposure, Greeks, snapshot history | risk-dashboard |
| 3.8 | **News** (`/news`) — streaming cards, sentiment, anomaly alerts | news-feed |

### Phase 4 — Secondary Pages
| Step | Task | Replaces |
|------|------|----------|
| 4.1 | **Bot Control** (`/bot`) — state machine UI, config, history | bot-panel |
| 4.2 | **Backtest** (`/backtest`) — form, job polling, results + equity chart | backtest |
| 4.3 | **Paper Trading** (`/paper`) — accounts, replay, order form | paper-dashboard, paper-account-detail |

### Phase 5 — Admin & Auth
| Step | Task | Replaces |
|------|------|----------|
| 5.1 | **Auth** (`/auth/login`) — login page, token flow | — |
| 5.2 | **System Admin** (`/system`) — models, drift, registry, canary sub-pages | admin, execution-quality |

### Phase 6 — Service Refactor
| Step | Task |
|------|------|
| 6.1 | Refactor services to use `core/models/` imports instead of inline interfaces |
| 6.2 | Split `market-api.service` → `market-data.service` + `bot.service` |
| 6.3 | Merge `live-stream.service` + `price-stream.service` → unified `price-stream.service` using `websocket.service` |
| 6.4 | Merge `execution-api.service` into `order.service` |
| 6.5 | Rename `intelligence-api.service` → `news.service`, `admin-api.service` → `system.service` |
| 6.6 | Create `position.service` + `holdings.service` (from portfolio-api split) |
| 6.7 | Add `cache.service` integration to all GET-based services |
| 6.8 | Add retry/backoff to all API services via rxjs `retry()` operator |

### Phase 7 — Polish
| Step | Task |
|------|------|
| 7.1 | Keyboard shortcuts (Ctrl+K: search, Ctrl+O: quick order, Ctrl+P: portfolio) |
| 7.2 | Responsive testing — mobile, tablet, desktop, ultrawide |
| 7.3 | Dark mode support via Bootstrap `data-bs-theme="dark"` |
| 7.4 | Performance audit — remove unused imports, check bundle size, lazy load images |
| 7.5 | Accessibility audit — ARIA labels, focus management, screen reader testing |

---

## PART 9 — KEY DECISIONS

| Decision | Choice | Reason |
|----------|--------|--------|
| CSS Framework | **Bootstrap 5.3** | User requirement. Mature, responsive grid, utility-first option via `@extend` |
| Chart Library | **TradingView Lightweight Charts** | Purpose-built for financial data, candlestick/line/area, fast WebGL rendering, free |
| Icon Library | **Bootstrap Icons** | Consistent with Bootstrap, 2000+ icons, SVG sprite |
| State Management | **RxJS BehaviorSubjects in services** | Sufficient for this scale, no NgRx overhead needed |
| Forms | **Reactive Forms** | Better validation, testability, dynamic form building |
| HTTP Caching | **Custom cache.service.ts** | TTL-based in-memory cache for GET requests, invalidate on mutations |
| Sass | **SCSS** | Required for Bootstrap customization via `$variables` |

---

## FILES TO DELETE AFTER REBUILD

Once each phase is complete and verified, remove the old files:

```
# Phase 3 completion — remove old pages:
pages/paper-dashboard.component.ts        → replaced by features/market-overview/
pages/live-market.component.ts            → replaced by features/market-overview/
pages/live-chart.component.ts             → replaced by features/chart/
pages/trading.component.ts                → replaced by features/trading/
pages/signal-explorer.component.ts        → replaced by features/predictions/
pages/signal-detail.component.ts          → merged into features/predictions/
pages/options-builder.component.ts        → replaced by features/options/
pages/risk-dashboard.component.ts         → replaced by features/risk/
pages/news-feed.component.ts              → replaced by features/news/
pages/portfolio-dashboard.component.ts    → replaced by features/portfolio/
pages/regime-panel.component.ts           → absorbed into market-overview widget

# Phase 4 completion:
pages/bot-panel.component.ts              → replaced by features/bot/
pages/backtest.component.ts               → replaced by features/backtest/
pages/paper-account-detail.component.ts   → replaced by features/paper/

# Phase 5 completion:
pages/admin.component.ts                  → replaced by features/system/
pages/execution-quality.component.ts      → merged into features/system/

# Phase 2 completion — remove old components:
components/equity-chart.component.ts      → replaced by shared/components/chart
components/live-price-chart.component.ts  → replaced by shared/components/chart
components/simulation-summary-card.component.ts → replaced by shared/components/stat-card
components/order-intent-form.component.ts → replaced by shared/components/order-form

# Phase 6 completion — remove old services:
services/live-stream.service.ts           → merged into core/services/price-stream.service
services/execution-api.service.ts         → merged into core/services/order.service
services/strategy-api.service.ts          → split into prediction.service + options.service
services/intelligence-api.service.ts      → renamed to news.service

# Keep (rename/move only):
components/sparkline.component.ts         → move to shared/components/
components/ticker-tape.component.ts       → move to shared/components/
```
