import {
  Directive,
  ElementRef,
  EventEmitter,
  NgZone,
  OnDestroy,
  OnInit,
  Output,
} from '@angular/core';

@Directive({
  selector: '[appClickOutside]',
  standalone: true,
})
export class ClickOutsideDirective implements OnInit, OnDestroy {
  @Output('appClickOutside') clickOutside = new EventEmitter<MouseEvent>();

  private listener!: (e: MouseEvent) => void;

  constructor(
    private el: ElementRef<HTMLElement>,
    private zone: NgZone,
  ) {}

  ngOnInit(): void {
    this.zone.runOutsideAngular(() => {
      this.listener = (event: MouseEvent) => {
        const target = event.target as HTMLElement;
        if (!target || !this.el.nativeElement.contains(target)) {
          this.zone.run(() => this.clickOutside.emit(event));
        }
      };
      // Use setTimeout to avoid catching the click that opens the element
      setTimeout(() => document.addEventListener('click', this.listener, true), 0);
    });
  }

  ngOnDestroy(): void {
    document.removeEventListener('click', this.listener, true);
  }
}
