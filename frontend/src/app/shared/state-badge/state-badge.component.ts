import { Component, ChangeDetectionStrategy, Input } from '@angular/core';
import { NgClass } from '@angular/common';
import { BadgeVariant } from '../models/ui.model';

const VARIANT_MAP: Record<BadgeVariant, string> = {
  // Trading actions
  buy:        'badge--buy',
  sell:       'badge--sell',
  hold:       'badge--hold',
  long:       'badge--buy',
  short:      'badge--sell',
  // Order status
  open:       'badge--info',
  filled:     'badge--success',
  pending:    'badge--warning',
  cancelled:  'badge--neutral',
  rejected:   'badge--danger',
  closed:     'badge--neutral',
  // System / bot
  running:    'badge--running',
  stopped:    'badge--neutral',
  error:      'badge--danger',
  // Market session
  'pre-open':   'badge--warning',
  'post-close': 'badge--neutral',
  // Generic
  success:    'badge--success',
  warning:    'badge--warning',
  danger:     'badge--danger',
  info:       'badge--info',
  neutral:    'badge--neutral',
};

@Component({
  selector: 'app-state-badge',
  standalone: true,
  imports: [NgClass],
  templateUrl: './state-badge.component.html',
  styleUrl: './state-badge.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StateBadgeComponent {
  @Input({ required: true }) variant!: BadgeVariant;
  @Input() label?: string;
  @Input() dot = false;
  @Input() uppercase = true;
  @Input() size: 'xs' | 'sm' | 'md' = 'sm';

  get badgeClass(): string {
    return VARIANT_MAP[this.variant] ?? 'badge--neutral';
  }

  get displayLabel(): string {
    return this.label ?? this.variant.replace(/-/g, ' ');
  }
}
