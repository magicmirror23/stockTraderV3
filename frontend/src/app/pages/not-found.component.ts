import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-not-found',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="nf">
      <div class="card nf__card">
        <h1 class="nf__title">Page Not Found</h1>
        <p class="text-muted mb-3">The page you requested does not exist or has been moved.</p>
        <a class="btn btn-primary" [routerLink]="['/']">Back to Dashboard</a>
      </div>
    </div>
  `,
  styles: [`
    .nf {
      min-height: calc(100vh - 56px);
      display: grid;
      place-items: center;
      padding: 1.5rem;
    }
    .nf__card {
      max-width: 520px;
      width: 100%;
      text-align: center;
      padding: 2rem 1.5rem;
    }
    .nf__title {
      font-size: 1.75rem;
      font-weight: 700;
      margin: 0 0 0.75rem;
    }
  `],
})
export class NotFoundComponent {}

