import { Component, ChangeDetectionStrategy, Input } from '@angular/core';
import { NgClass } from '@angular/common';
import { TrendDirection } from '../models/ui.model';

@Component({
  selector: 'app-stat-card',
  standalone: true,
  imports: [NgClass],
  templateUrl: './stat-card.component.html',
  styleUrl: './stat-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatCardComponent {
  @Input({ required: true }) label!: string;
  @Input({ required: true }) value!: string | number;
  @Input() delta?: string | number;
  @Input() deltaSuffix = '';
  @Input() icon?: string;
  @Input() trend: TrendDirection = 'flat';
  @Input() muted = false;

  get trendIcon(): string {
    switch (this.trend) {
      case 'up':   return 'bi-caret-up-fill';
      case 'down': return 'bi-caret-down-fill';
      default:     return 'bi-dash';
    }
  }

  get trendClass(): string {
    switch (this.trend) {
      case 'up':   return 'text-buy';
      case 'down': return 'text-sell';
      default:     return 'text-hold';
    }
  }
}
