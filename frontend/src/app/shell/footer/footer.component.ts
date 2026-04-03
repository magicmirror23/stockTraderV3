import { Component, Input, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-footer',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './footer.component.html',
  styleUrl: './footer.component.scss',
})
export class FooterComponent implements OnInit, OnDestroy {
  @Input() marketPhase = 'closed';
  @Input() connected = false;
  @Input() apiStatus = 'ok';

  clock = '';
  private clockTimer: ReturnType<typeof setInterval> | null = null;

  get connectionLabel(): string {
    return this.connected ? 'Connected' : 'Disconnected';
  }

  get connectionDotClass(): string {
    return this.connected ? 'dot-ok' : 'dot-offline';
  }

  ngOnInit(): void {
    this.updateClock();
    this.clockTimer = setInterval(() => this.updateClock(), 1000);
  }

  ngOnDestroy(): void {
    if (this.clockTimer) {
      clearInterval(this.clockTimer);
    }
  }

  private updateClock(): void {
    const now = new Date();
    this.clock = now.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  }
}
