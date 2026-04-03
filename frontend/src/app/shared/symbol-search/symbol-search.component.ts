import {
  Component,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  ElementRef,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgClass } from '@angular/common';
import { Subject, Subscription, debounceTime, distinctUntilChanged } from 'rxjs';
import { SymbolResult } from '../models/interactive.model';
import { ClickOutsideDirective } from '../directives/click-outside.directive';
import { AutofocusDirective } from '../directives/autofocus.directive';

@Component({
  selector: 'app-symbol-search',
  standalone: true,
  imports: [FormsModule, NgClass, ClickOutsideDirective, AutofocusDirective],
  templateUrl: './symbol-search.component.html',
  styleUrl: './symbol-search.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SymbolSearchComponent implements OnInit, OnDestroy {
  /** Placeholder text */
  @Input() placeholder = 'Search symbol… (Ctrl+K)';
  /** Debounce interval in ms */
  @Input() debounceMs = 200;
  /** Maximum visible suggestions */
  @Input() maxResults = 12;

  /** Fired on each debounced query change — host should feed results back */
  @Output() queryChange = new EventEmitter<string>();
  /** Fired when user selects a symbol */
  @Output() symbolSelect = new EventEmitter<SymbolResult>();

  @ViewChild('searchInput') searchInput!: ElementRef<HTMLInputElement>;

  query = '';
  results: SymbolResult[] = [];
  activeIndex = -1;
  isOpen = false;
  loading = false;

  private query$ = new Subject<string>();
  private sub!: Subscription;

  constructor(private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    this.sub = this.query$
      .pipe(debounceTime(this.debounceMs), distinctUntilChanged())
      .subscribe((q) => {
        this.queryChange.emit(q);
      });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  /** Host calls this to push async results */
  setResults(results: SymbolResult[]): void {
    this.results = results.slice(0, this.maxResults);
    this.activeIndex = results.length > 0 ? 0 : -1;
    this.loading = false;
    this.isOpen = this.results.length > 0 || this.query.length > 0;
    this.cdr.markForCheck();
  }

  /** Host calls this to set loading state */
  setLoading(loading: boolean): void {
    this.loading = loading;
    this.cdr.markForCheck();
  }

  onInput(): void {
    const trimmed = this.query.trim();
    if (trimmed.length > 0) {
      this.loading = true;
      this.isOpen = true;
      this.query$.next(trimmed);
    } else {
      this.close();
    }
  }

  onKeyDown(event: KeyboardEvent): void {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (this.activeIndex < this.results.length - 1) {
          this.activeIndex++;
        }
        break;
      case 'ArrowUp':
        event.preventDefault();
        if (this.activeIndex > 0) {
          this.activeIndex--;
        }
        break;
      case 'Enter':
        event.preventDefault();
        if (this.activeIndex >= 0 && this.activeIndex < this.results.length) {
          this.select(this.results[this.activeIndex]);
        }
        break;
      case 'Escape':
        this.close();
        break;
      case 'Tab':
        this.close();
        break;
    }
  }

  select(result: SymbolResult): void {
    this.symbolSelect.emit(result);
    this.query = result.symbol;
    this.close();
  }

  close(): void {
    this.isOpen = false;
    this.results = [];
    this.activeIndex = -1;
    this.loading = false;
    this.cdr.markForCheck();
  }

  open(): void {
    this.searchInput?.nativeElement.focus();
    if (this.query.trim().length > 0) {
      this.isOpen = true;
      this.cdr.markForCheck();
    }
  }

  clear(): void {
    this.query = '';
    this.close();
    this.searchInput?.nativeElement.focus();
  }

  trackBySymbol(_: number, item: SymbolResult): string {
    return item.symbol;
  }
}
