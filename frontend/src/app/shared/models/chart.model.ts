/** Chart-related interfaces for lightweight-charts integration */

import type {
  CandlestickData,
  LineData,
  HistogramData,
  Time,
} from 'lightweight-charts';

// Re-export lightweight-charts types for convenience
export type { CandlestickData, LineData, HistogramData, Time };

export type ChartMode = 'line' | 'area' | 'candlestick';

export interface ChartTheme {
  background: string;
  textColor: string;
  gridColor: string;
  borderColor: string;
  crosshairColor: string;
  upColor: string;
  downColor: string;
  wickUpColor: string;
  wickDownColor: string;
  lineColor: string;
  areaTopColor: string;
  areaBottomColor: string;
}

export const CHART_THEME_LIGHT: ChartTheme = {
  background: '#ffffff',
  textColor: '#333333',
  gridColor: '#f0f0f0',
  borderColor: '#e0e0e0',
  crosshairColor: '#9e9e9e',
  upColor: '#2e7d32',
  downColor: '#d32f2f',
  wickUpColor: '#2e7d32',
  wickDownColor: '#d32f2f',
  lineColor: '#1976d2',
  areaTopColor: 'rgba(25, 118, 210, 0.28)',
  areaBottomColor: 'rgba(25, 118, 210, 0.02)',
};

export const CHART_THEME_DARK: ChartTheme = {
  background: '#1e1e1e',
  textColor: '#d4d4d4',
  gridColor: '#2a2a2a',
  borderColor: '#333333',
  crosshairColor: '#666666',
  upColor: '#4caf50',
  downColor: '#ef5350',
  wickUpColor: '#4caf50',
  wickDownColor: '#ef5350',
  lineColor: '#42a5f5',
  areaTopColor: 'rgba(66, 165, 245, 0.28)',
  areaBottomColor: 'rgba(66, 165, 245, 0.02)',
};

export interface OhlcBar {
  time: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface PricePoint {
  time: string | number;
  value: number;
}

export interface VolumeBar {
  time: string | number;
  value: number;
  color?: string;
}

export interface TickerTapeItem {
  symbol: string;
  price: number;
  change: number;
  changePct: number;
}
