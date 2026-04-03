import {
  Directive,
  ElementRef,
  AfterViewInit,
  Input,
} from '@angular/core';

@Directive({
  selector: '[appAutofocus]',
  standalone: true,
})
export class AutofocusDirective implements AfterViewInit {
  @Input('appAutofocus') enabled: boolean | '' = true;

  constructor(private el: ElementRef<HTMLElement>) {}

  ngAfterViewInit(): void {
    if (this.enabled !== false) {
      // Defer to next microtask so element is fully rendered
      Promise.resolve().then(() => this.el.nativeElement.focus());
    }
  }
}
