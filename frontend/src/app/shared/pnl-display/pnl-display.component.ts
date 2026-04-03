import { Component, ChangeDetectionStrategy, Input } from '@angular/core';
import { DecimalPipe, NgClass } from '@angular/common';

@Component({
  selector: 'app-pnl-display',
  standalone: true,
  imports: [DecimalPipe, NgClass],
  templateUrl: './pnl-display.component.html',
  styleUrl: './pnl-display.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PnlDisplayComponent {
  @Input({ required: true }) value!: number;
  @Input() label?: string;
  @Input() showSign = true;
  @Input() format = '1.2-2';
  @Input() size: 'sm' | 'md' | 'lg' = 'md';
  @Input() pill = false;

  get sentiment(): 'positive' | 'negative' | 'neutral' {
    if (this.value > 0) return 'positive';
    if (this.value < 0) return 'negative';
    return 'neutral';
  }

  get prefix(): string {
    if (!this.showSign) return '';
    if (this.value > 0) return '+';
    return '';                 // negative sign from number pipe
  }

  get sentimentClass(): string {
    return 'pnl--' + this.sentiment;
  }
}
