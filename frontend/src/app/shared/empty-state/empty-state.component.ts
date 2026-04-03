import { Component, ChangeDetectionStrategy, Input, Output, EventEmitter } from '@angular/core';
import { NgClass } from '@angular/common';

@Component({
  selector: 'app-empty-state',
  standalone: true,
  imports: [NgClass],
  templateUrl: './empty-state.component.html',
  styleUrl: './empty-state.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EmptyStateComponent {
  @Input() icon = 'inbox';                  // bootstrap-icons name (no 'bi-' prefix)
  @Input() title = 'No data';
  @Input() message = '';
  @Input() actionLabel?: string;
  @Input() actionIcon?: string;
  @Input() actionVariant = 'outline-primary';
  @Input() compact = false;

  @Output() action = new EventEmitter<void>();

  onAction(): void {
    this.action.emit();
  }
}
