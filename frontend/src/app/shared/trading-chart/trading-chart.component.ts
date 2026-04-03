import {
  Component,
  ChangeDetectionStrategy,
  Input,
  Output,
  EventEmitter,
  ElementRef,
  ViewChild,
  AfterViewInit,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  NgZone,
} from '@angular/core';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CrosshairMode,
  LineStyle,
  ColorType,
} from 'lightweight-charts';
import {
  ChartMode,
  ChartTheme,
  OhlcBar,
  PricePoint,
  VolumeBar,
  CHART_THEME_LIGHT,
} from '../models/chart.model';

@Component({
  selector: 'app-trading-chart',
  standalone: true,
  templateUrl: './trading-chart.component.html',
  styleUrl: './trading-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TradingChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('chartContainer', { static: true }) containerRef!: ElementRef<HTMLDivElement>;

  /** Chart display mode */
  @Input() mode: ChartMode = 'candlestick';

  /** OHLC data for candlestick mode */
  @Input() ohlcData: OhlcBar[] = [];

  /** Line/area data */
  @Input() lineData: PricePoint[] = [];

  /** Volume overlay data */
  @Input() volumeData: VolumeBar[] = [];

  /** Chart height in px (width is always 100%) */
  @Input() height = 400;

  /** Theme configuration */
  @Input() theme: ChartTheme = CHART_THEME_LIGHT;

  /** Show volume histogram */
  @Input() showVolume = true;

  /** Show crosshair */
  @Input() showCrosshair = true;

  /** Time scale visible flag */
  @Input() showTimeScale = true;

  /** Price scale visible flag */
  @Input() showPriceScale = true;

  /** Auto-fit content on data change */
  @Input() autoFit = true;

  /** Emits crosshair hover data */
  @Output() crosshairMove = new EventEmitter<{ time: any; price: number | null }>();

  private chart: IChartApi | null = null;
  private mainSeries: ISeriesApi<any> | null = null;
  private volumeSeries: ISeriesApi<'Histogram'> | null = null;
  private resizeObserver: ResizeObserver | null = null;

  constructor(private ngZone: NgZone) {}

  ngAfterViewInit(): void {
    this.ngZone.runOutsideAngular(() => {
      this.createChart();
      this.setupResizeObserver();
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.chart) return;

    if (changes['mode'] || changes['theme']) {
      this.rebuildChart();
      return;
    }

    if (changes['ohlcData'] || changes['lineData']) {
      this.updateSeriesData();
    }

    if (changes['volumeData']) {
      this.updateVolumeData();
    }

    if (changes['height']) {
      this.chart.resize(this.containerRef.nativeElement.clientWidth, this.height);
    }
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.chart?.remove();
    this.chart = null;
  }

  /** Programmatically fit all visible content */
  fitContent(): void {
    this.chart?.timeScale().fitContent();
  }

  /** Scroll to the most recent bar */
  scrollToRealtime(): void {
    this.chart?.timeScale().scrollToRealTime();
  }

  private createChart(): void {
    const container = this.containerRef.nativeElement;
    const t = this.theme;

    this.chart = createChart(container, {
      width: container.clientWidth,
      height: this.height,
      layout: {
        background: { type: ColorType.Solid, color: t.background },
        textColor: t.textColor,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: t.gridColor },
        horzLines: { color: t.gridColor },
      },
      crosshair: {
        mode: this.showCrosshair ? CrosshairMode.Normal : CrosshairMode.Hidden,
        vertLine: {
          color: t.crosshairColor,
          style: LineStyle.Dashed,
          width: 1,
          labelBackgroundColor: t.crosshairColor,
        },
        horzLine: {
          color: t.crosshairColor,
          style: LineStyle.Dashed,
          width: 1,
          labelBackgroundColor: t.crosshairColor,
        },
      },
      rightPriceScale: {
        visible: this.showPriceScale,
        borderColor: t.borderColor,
      },
      timeScale: {
        visible: this.showTimeScale,
        borderColor: t.borderColor,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale: true,
    });

    this.createSeries();
    this.updateSeriesData();
    this.updateVolumeData();

    if (this.autoFit) {
      this.chart.timeScale().fitContent();
    }

    // Crosshair events
    this.chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point) return;
      const series = this.mainSeries;
      if (!series) return;
      const data = param.seriesData.get(series);
      const price = data ? ((data as any).close ?? (data as any).value ?? null) : null;
      this.ngZone.run(() => {
        this.crosshairMove.emit({ time: param.time, price });
      });
    });
  }

  private createSeries(): void {
    if (!this.chart) return;
    const t = this.theme;

    switch (this.mode) {
      case 'candlestick':
        this.mainSeries = this.chart.addCandlestickSeries({
          upColor: t.upColor,
          downColor: t.downColor,
          wickUpColor: t.wickUpColor,
          wickDownColor: t.wickDownColor,
          borderVisible: false,
        });
        break;

      case 'area':
        this.mainSeries = this.chart.addAreaSeries({
          lineColor: t.lineColor,
          topColor: t.areaTopColor,
          bottomColor: t.areaBottomColor,
          lineWidth: 2,
        });
        break;

      case 'line':
        this.mainSeries = this.chart.addLineSeries({
          color: t.lineColor,
          lineWidth: 2,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 4,
        });
        break;
    }

    if (this.showVolume) {
      this.volumeSeries = this.chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      this.chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
    }
  }

  private updateSeriesData(): void {
    if (!this.mainSeries) return;

    if (this.mode === 'candlestick' && this.ohlcData.length) {
      this.mainSeries.setData(
        this.ohlcData.map((d) => ({
          time: d.time as any,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }))
      );
    } else if ((this.mode === 'line' || this.mode === 'area') && this.lineData.length) {
      this.mainSeries.setData(
        this.lineData.map((d) => ({ time: d.time as any, value: d.value }))
      );
    }

    if (this.autoFit) {
      this.chart?.timeScale().fitContent();
    }
  }

  private updateVolumeData(): void {
    if (!this.volumeSeries || !this.volumeData.length) return;
    const t = this.theme;

    this.volumeSeries.setData(
      this.volumeData.map((d) => ({
        time: d.time as any,
        value: d.value,
        color: d.color ?? (d.value >= 0 ? t.upColor + '33' : t.downColor + '33'),
      }))
    );
  }

  private rebuildChart(): void {
    this.chart?.remove();
    this.chart = null;
    this.mainSeries = null;
    this.volumeSeries = null;
    this.ngZone.runOutsideAngular(() => this.createChart());
  }

  private setupResizeObserver(): void {
    const container = this.containerRef.nativeElement;
    this.resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        if (width > 0 && this.chart) {
          this.chart.resize(width, this.height);
        }
      }
    });
    this.resizeObserver.observe(container);
  }
}
