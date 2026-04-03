import {
  Component,
  ChangeDetectionStrategy,
  EventEmitter,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
} from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { NgClass, UpperCasePipe, DecimalPipe } from '@angular/common';
import {
  OrderSide,
  OrderType,
  ProductType,
  OrderFormPayload,
  OrderFormConfig,
} from '../models/interactive.model';

@Component({
  selector: 'app-order-form',
  standalone: true,
  imports: [ReactiveFormsModule, NgClass, UpperCasePipe, DecimalPipe],
  templateUrl: './order-form.component.html',
  styleUrl: './order-form.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrderFormComponent implements OnInit, OnChanges {
  @Input() config: OrderFormConfig = {};
  @Input() loading = false;
  @Input() disabled = false;

  @Output() submitOrder = new EventEmitter<OrderFormPayload>();

  form!: FormGroup;

  orderTypes: OrderType[] = ['market', 'limit', 'stop', 'stop-limit'];
  productTypes: ProductType[] = ['CNC', 'MIS', 'NRML'];

  constructor(private fb: FormBuilder) {}

  ngOnInit(): void {
    this.buildForm();
    this.applyConfig();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['config'] && !changes['config'].firstChange) {
      this.applyConfig();
    }
  }

  get side(): OrderSide {
    return this.form?.get('side')?.value ?? 'buy';
  }

  get orderType(): OrderType {
    return this.form?.get('orderType')?.value ?? 'market';
  }

  get showPrice(): boolean {
    return this.orderType === 'limit' || this.orderType === 'stop-limit';
  }

  get showTriggerPrice(): boolean {
    return this.orderType === 'stop' || this.orderType === 'stop-limit';
  }

  get lotSize(): number {
    return this.config.lotSize ?? 1;
  }

  get tickSize(): number {
    return this.config.tickSize ?? 0.05;
  }

  get estimatedValue(): number {
    const qty = this.form?.get('quantity')?.value || 0;
    const price = this.form?.get('price')?.value || this.config.lastPrice || 0;
    return qty * price;
  }

  toggleSide(side: OrderSide): void {
    this.form.patchValue({ side });
  }

  onSubmit(): void {
    if (this.form.invalid || this.loading || this.disabled) return;

    this.form.markAllAsTouched();

    const raw = this.form.getRawValue();
    const payload: OrderFormPayload = {
      symbol: raw.symbol,
      side: raw.side,
      orderType: raw.orderType,
      quantity: raw.quantity,
      price: this.showPrice ? raw.price : null,
      triggerPrice: this.showTriggerPrice ? raw.triggerPrice : null,
      productType: raw.productType,
    };

    this.submitOrder.emit(payload);
  }

  incrementQty(): void {
    const ctrl = this.form.get('quantity')!;
    const max = this.config.maxQuantity ?? Infinity;
    ctrl.setValue(Math.min(ctrl.value + this.lotSize, max));
  }

  decrementQty(): void {
    const ctrl = this.form.get('quantity')!;
    ctrl.setValue(Math.max(ctrl.value - this.lotSize, this.lotSize));
  }

  hasError(field: string, error: string): boolean {
    const ctrl = this.form.get(field);
    return !!ctrl && ctrl.hasError(error) && ctrl.touched;
  }

  private buildForm(): void {
    this.form = this.fb.group({
      symbol: ['', Validators.required],
      side: ['buy' as OrderSide],
      orderType: ['market' as OrderType],
      quantity: [1, [Validators.required, Validators.min(1)]],
      price: [null as number | null],
      triggerPrice: [null as number | null],
      productType: ['CNC' as ProductType],
    });

    // Dynamically toggle price/trigger validators
    this.form.get('orderType')!.valueChanges.subscribe((type: OrderType) => {
      this.updatePriceValidators(type);
    });
  }

  private applyConfig(): void {
    if (!this.form) return;

    const c = this.config;
    if (c.symbol) this.form.patchValue({ symbol: c.symbol });
    if (c.side) this.form.patchValue({ side: c.side });
    if (c.lastPrice && !this.form.get('price')?.value) {
      this.form.patchValue({ price: c.lastPrice });
    }
    if (c.allowedOrderTypes?.length) this.orderTypes = c.allowedOrderTypes;
    if (c.allowedProductTypes?.length) this.productTypes = c.allowedProductTypes;

    const qty = this.form.get('quantity')!;
    qty.setValidators([
      Validators.required,
      Validators.min(c.lotSize ?? 1),
      ...(c.maxQuantity ? [Validators.max(c.maxQuantity)] : []),
    ]);
    qty.updateValueAndValidity();

    this.updatePriceValidators(this.form.get('orderType')!.value);
  }

  private updatePriceValidators(type: OrderType): void {
    const price = this.form.get('price')!;
    const trigger = this.form.get('triggerPrice')!;

    if (type === 'limit' || type === 'stop-limit') {
      price.setValidators([Validators.required, Validators.min(this.tickSize)]);
    } else {
      price.clearValidators();
    }

    if (type === 'stop' || type === 'stop-limit') {
      trigger.setValidators([Validators.required, Validators.min(this.tickSize)]);
    } else {
      trigger.clearValidators();
    }

    price.updateValueAndValidity({ emitEvent: false });
    trigger.updateValueAndValidity({ emitEvent: false });
  }
}
