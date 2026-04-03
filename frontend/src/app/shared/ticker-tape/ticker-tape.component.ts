import {
  Component,
  ChangeDetectionStrategy,
  Input,
  OnChanges,
  SimpleChanges,
  ChangeDetectorRef,
} from '@angular/core';
import { DecimalPipe, NgClass } from '@angular/common';
import { TickerTapeItem } from '../models/chart.model';

@Component({
  selector: 'app-ticker-tape',
  standalone: true,
  imports: [DecimalPipe, NgClass],
  templateUrl: './ticker-tape.component.html',
  styleUrl: './ticker-tape.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TickerTapeComponent implements OnChanges {
  /** Ticker items to display */
  @Input() items: TickerTapeItem[] = [];

  /** Animation speed in px/s */
  @Input() speed = 40;

  /** Pause scrolling on hover */
  @Input() pauseOnHover = true;

  /** Duplicate items for seamless infinite scroll */
  displayItems: TickerTapeItem[] = [];

  /** CSS animation duration in seconds */
  animDuration = '30s';

  constructor(private cdr: ChangeDetectorRef) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['items'] || changes['speed']) {
      this.displayItems = [...this.items, ...this.items];
      // Estimate total width: ~160px per item, calculate duration for smooth scroll
      const totalWidth = this.items.length * 160;
      const duration = this.speed > 0 ? totalWidth / this.speed : 30;
      this.animDuration = `${Math.max(duration, 5)}s`;
      this.cdr.markForCheck();
    }
  }

  direction(item: TickerTapeItem): 'up' | 'down' | 'flat' {
    if (item.changePct > 0) return 'up';
    if (item.changePct < 0) return 'down';
    return 'flat';
  }

  arrow(item: TickerTapeItem): string {
    if (item.changePct > 0) return '▲';
    if (item.changePct < 0) return '▼';
    return '';
  }

  trackBySymbol(_: number, item: TickerTapeItem): string {
    return item.symbol;
  }
}
