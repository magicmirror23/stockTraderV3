import {
  Component,
  ChangeDetectionStrategy,
  Input,
  ElementRef,
  ViewChild,
  AfterViewInit,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  NgZone,
} from '@angular/core';
import { createChart, IChartApi, ISeriesApi, ColorType } from 'lightweight-charts';

@Component({
  selector: 'app-sparkline',
  standalone: true,
  templateUrl: './sparkline.component.html',
  styleUrl: './sparkline.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SparklineComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('spark', { static: true }) containerRef!: ElementRef<HTMLDivElement>;

  /** Array of numeric values */
  @Input() data: number[] = [];

  /** Width in px (default 80) */
  @Input() width = 80;

  /** Height in px (default 28) */
  @Input() height = 28;

  /** Line color — auto-detects trend if set to 'auto' */
  @Input() color: string | 'auto' = 'auto';

  /** Fill area under the line */
  @Input() fill = true;

  private chart: IChartApi | null = null;
  private series: ISeriesApi<'Area'> | null = null;

  private readonly UP_COLOR = '#2e7d32';
  private readonly DOWN_COLOR = '#d32f2f';
  private readonly FLAT_COLOR = '#757575';

  constructor(private ngZone: NgZone) {}

  ngAfterViewInit(): void {
    this.ngZone.runOutsideAngular(() => this.createChart());
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.chart) return;

    if (changes['width'] || changes['height']) {
      this.chart.resize(this.width, this.height);
    }
    if (changes['data'] || changes['color'] || changes['fill']) {
      this.updateData();
    }
  }

  ngOnDestroy(): void {
    this.chart?.remove();
    this.chart = null;
  }

  private get resolvedColor(): string {
    if (this.color !== 'auto') return this.color;
    if (this.data.length < 2) return this.FLAT_COLOR;
    const first = this.data[0];
    const last = this.data[this.data.length - 1];
    if (last > first) return this.UP_COLOR;
    if (last < first) return this.DOWN_COLOR;
    return this.FLAT_COLOR;
  }

  private createChart(): void {
    const container = this.containerRef.nativeElement;

    this.chart = createChart(container, {
      width: this.width,
      height: this.height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'transparent',
        fontFamily: 'sans-serif',
        fontSize: 1,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      rightPriceScale: { visible: false },
      timeScale: {
        visible: false,
        borderVisible: false,
      },
      handleScroll: false,
      handleScale: false,
      crosshair: {
        vertLine: { visible: false },
        horzLine: { visible: false },
      },
    });

    this.series = this.chart.addAreaSeries({
      lineWidth: 1,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    this.updateData();
  }

  private updateData(): void {
    if (!this.series || this.data.length < 2) return;
    const c = this.resolvedColor;

    this.series.applyOptions({
      lineColor: c,
      topColor: this.fill ? c + '30' : 'transparent',
      bottomColor: 'transparent',
    });

    // Use sequential integer timestamps for sparkline points
    this.series.setData(
      this.data.map((value, i) => ({
        time: (i + 1) as any,
        value,
      }))
    );

    this.chart?.timeScale().fitContent();
  }
}
