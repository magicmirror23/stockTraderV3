import { Component, ChangeDetectionStrategy, Input } from '@angular/core';
import { DecimalPipe, NgClass } from '@angular/common';

@Component({
  selector: 'app-price-display',
  standalone: true,
  imports: [DecimalPipe, NgClass],
  templateUrl: './price-display.component.html',
  styleUrl: './price-display.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PriceDisplayComponent {
  @Input({ required: true }) price!: number;
  @Input() change?: number;
  @Input() changePct?: number;
  @Input() prevClose?: number;
  @Input() size: 'sm' | 'md' | 'lg' = 'md';
  @Input() inline = false;

  get direction(): 'up' | 'down' | 'flat' {
    const c = this.effectiveChange;
    if (c > 0) return 'up';
    if (c < 0) return 'down';
    return 'flat';
  }

  get effectiveChange(): number {
    if (this.change !== undefined) return this.change;
    if (this.prevClose !== undefined) return this.price - this.prevClose;
    return 0;
  }

  get effectiveChangePct(): number {
    if (this.changePct !== undefined) return this.changePct;
    if (this.prevClose && this.prevClose !== 0) {
      return ((this.price - this.prevClose) / this.prevClose) * 100;
    }
    return 0;
  }

  get dirClass(): string {
    switch (this.direction) {
      case 'up':   return 'price--up';
      case 'down': return 'price--down';
      default:     return 'price--flat';
    }
  }

  get arrow(): string {
    switch (this.direction) {
      case 'up':   return '▲';
      case 'down': return '▼';
      default:     return '';
    }
  }
}
