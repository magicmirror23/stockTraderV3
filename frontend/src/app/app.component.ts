// Root Angular component — minimal shell; layout lives in ShellComponent

import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { NotificationService, Toast } from './services/notification.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    <router-outlet />

    <!-- Global toast overlay -->
    <div class="st-toast-container">
      @for (t of toasts; track t.id) {
        <div class="st-toast" [ngClass]="'st-toast-' + t.type" (click)="notify.remove(t.id)">
          {{ t.message }}
        </div>
      }
    </div>
  `,
  styles: [`
    .st-toast-container {
      position: fixed;
      top: 1rem;
      right: 1rem;
      z-index: 10000;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      pointer-events: none;
    }
    .st-toast {
      pointer-events: auto;
      padding: 0.75rem 1.25rem;
      border-radius: var(--radius);
      color: #fff;
      font-size: 0.875rem;
      box-shadow: var(--shadow-lg);
      animation: slideIn 0.3s ease;
      max-width: 400px;
      cursor: pointer;
    }
    .st-toast-success { background: var(--color-success); }
    .st-toast-error   { background: var(--color-danger); }
    .st-toast-info    { background: var(--color-info); }
    .st-toast-warning { background: var(--color-warning); }
    @keyframes slideIn {
      from { transform: translateX(100%); opacity: 0; }
      to   { transform: translateX(0);    opacity: 1; }
    }
  `],
})
export class AppComponent {
  toasts: Toast[] = [];

  constructor(public notify: NotificationService) {
    this.notify.toasts$.subscribe(t => this.toasts = t);
  }
}


