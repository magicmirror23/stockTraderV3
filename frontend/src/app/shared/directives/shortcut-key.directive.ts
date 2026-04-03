import {
  Directive,
  EventEmitter,
  HostListener,
  Input,
  Output,
} from '@angular/core';
import { ShortcutDef } from '../models/interactive.model';

@Directive({
  selector: '[appShortcutKey]',
  standalone: true,
})
export class ShortcutKeyDirective {
  @Input({ required: true, alias: 'appShortcutKey' }) shortcut!: ShortcutDef;
  @Output() shortcutTriggered = new EventEmitter<KeyboardEvent>();

  @HostListener('document:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if (!this.shortcut) return;

    // Don't fire when user is typing in an input/textarea/contenteditable
    const tag = (event.target as HTMLElement)?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (event.target as HTMLElement)?.isContentEditable) {
      // Allow Escape always
      if (this.shortcut.key !== 'Escape') return;
    }

    const keyMatch = event.key.toLowerCase() === this.shortcut.key.toLowerCase();
    const ctrlMatch = !!this.shortcut.ctrl === (event.ctrlKey || event.metaKey);
    const shiftMatch = !!this.shortcut.shift === event.shiftKey;
    const altMatch = !!this.shortcut.alt === event.altKey;

    if (keyMatch && ctrlMatch && shiftMatch && altMatch) {
      event.preventDefault();
      event.stopPropagation();
      this.shortcutTriggered.emit(event);
    }
  }
}
