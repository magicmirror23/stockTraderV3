import { Component, ChangeDetectionStrategy } from '@angular/core';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-intraday-shell',
  standalone: true,
  imports: [RouterModule],
  templateUrl: './intraday-shell.component.html',
  styleUrl: './intraday-shell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class IntradayShellComponent {}
