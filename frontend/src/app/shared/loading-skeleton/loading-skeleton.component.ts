import { Component, ChangeDetectionStrategy, Input } from '@angular/core';
import { NgClass } from '@angular/common';
import { SkeletonShape } from '../models/ui.model';

@Component({
  selector: 'app-loading-skeleton',
  standalone: true,
  imports: [NgClass],
  templateUrl: './loading-skeleton.component.html',
  styleUrl: './loading-skeleton.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoadingSkeletonComponent {
  @Input() shape: SkeletonShape = 'card';
  @Input() repeat = 1;
  @Input() height?: string;       // override height, e.g. '200px'
  @Input() width?: string;        // override width
  @Input() rows = 4;              // for 'table' shape
  @Input() columns = 4;           // for 'table' shape

  get items(): number[] {
    return Array.from({ length: this.repeat }, (_, i) => i);
  }

  get tableRows(): number[] {
    return Array.from({ length: this.rows }, (_, i) => i);
  }

  get tableCols(): number[] {
    return Array.from({ length: this.columns }, (_, i) => i);
  }
}
