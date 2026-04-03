/** Shared UI components & models barrel export */

// UI Models
export { TrendDirection, StatCardConfig, BadgeVariant, SkeletonShape, EmptyStateAction } from './models/ui.model';

// Chart Models
export {
  ChartMode, ChartTheme, OhlcBar, PricePoint, VolumeBar, TickerTapeItem,
  CHART_THEME_LIGHT, CHART_THEME_DARK,
} from './models/chart.model';

// Interactive Models
export {
  SymbolResult, OrderSide, OrderType, ProductType,
  OrderFormPayload, OrderFormConfig,
  ConfirmSeverity, ConfirmDialogConfig, ShortcutDef,
} from './models/interactive.model';

// Data Display Components
export { StatCardComponent } from './stat-card/stat-card.component';
export { PriceDisplayComponent } from './price-display/price-display.component';
export { PnlDisplayComponent } from './pnl-display/pnl-display.component';
export { StateBadgeComponent } from './state-badge/state-badge.component';
export { LoadingSkeletonComponent } from './loading-skeleton/loading-skeleton.component';
export { EmptyStateComponent } from './empty-state/empty-state.component';

// Chart & Market Components
export { TradingChartComponent } from './trading-chart/trading-chart.component';
export { SparklineComponent } from './sparkline/sparkline.component';
export { TickerTapeComponent } from './ticker-tape/ticker-tape.component';

// Interactive Components
export { SymbolSearchComponent } from './symbol-search/symbol-search.component';
export { OrderFormComponent } from './order-form/order-form.component';
export { ConfirmDialogComponent } from './confirm-dialog/confirm-dialog.component';

// Directives
export { ClickOutsideDirective } from './directives/click-outside.directive';
export { AutofocusDirective } from './directives/autofocus.directive';
export { ShortcutKeyDirective } from './directives/shortcut-key.directive';
