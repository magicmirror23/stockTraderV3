import {
  Component,
  ChangeDetectionStrategy,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { ConfirmSeverity } from '../models/interactive.model';

@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [NgClass],
  templateUrl: './confirm-dialog.component.html',
  styleUrl: './confirm-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfirmDialogComponent {
  @Input({ required: true }) title!: string;
  @Input({ required: true }) message!: string;
  @Input() confirmLabel = 'Confirm';
  @Input() cancelLabel = 'Cancel';
  @Input() severity: ConfirmSeverity = 'info';
  @Input() confirmIcon?: string;
  @Input() loading = false;
  @Input() open = false;

  @Output() confirm = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();

  get severityIcon(): string {
    switch (this.severity) {
      case 'danger':  return 'bi-exclamation-octagon';
      case 'warning': return 'bi-exclamation-triangle';
      default:        return 'bi-info-circle';
    }
  }

  get confirmBtnClass(): string {
    switch (this.severity) {
      case 'danger':  return 'btn--danger';
      case 'warning': return 'btn--warning';
      default:        return 'btn--primary';
    }
  }

  onConfirm(): void {
    if (!this.loading) {
      this.confirm.emit();
    }
  }

  onCancel(): void {
    if (!this.loading) {
      this.cancel.emit();
    }
  }

  onBackdropClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('confirm-dialog__backdrop')) {
      this.onCancel();
    }
  }

  onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      this.onCancel();
    }
  }
}
