"""Execution quality analytics and trade execution improvements.

Tracks slippage, fill quality, latency, and provides intelligent
order-type selection (limit vs market) and price protection.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionConfig:
    """Execution quality parameters."""
    max_slippage_pct: float = 0.005  # 0.5% max slippage
    price_protection_band_pct: float = 0.01  # reject if price moves >1% since signal
    prefer_limit_confidence: float = 0.8  # use limit orders for high-confidence trades
    limit_offset_pct: float = 0.001  # place limit 0.1% from current price
    max_retries: int = 3
    retry_delay: float = 0.5
    partial_fill_min_pct: float = 0.5  # accept partial fills >=50%
    liquidity_min_volume: int = 10_000  # min daily volume for liquid stocks
    option_spread_max_pct: float = 0.05  # max bid-ask spread for options


@dataclass
class ExecutionReport:
    """Post-execution quality report."""
    order_id: str = ""
    ticker: str = ""
    side: str = ""
    quantity: int = 0
    requested_price: float = 0.0
    filled_price: float = 0.0
    slippage_pct: float = 0.0
    slippage_amount: float = 0.0
    latency_ms: float = 0.0
    fill_quality: float = 1.0  # 0-1, 1 = perfect fill
    is_partial: bool = False
    filled_quantity: int = 0
    order_type_used: str = "market"
    retries: int = 0
    execution_reason: str = ""
    price_protection_triggered: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "ticker": self.ticker,
            "side": self.side,
            "quantity": self.quantity,
            "requested_price": round(self.requested_price, 2),
            "filled_price": round(self.filled_price, 2),
            "slippage_pct": round(self.slippage_pct, 4),
            "slippage_amount": round(self.slippage_amount, 2),
            "latency_ms": round(self.latency_ms, 1),
            "fill_quality": round(self.fill_quality, 3),
            "is_partial": self.is_partial,
            "filled_quantity": self.filled_quantity,
            "order_type_used": self.order_type_used,
            "retries": self.retries,
            "execution_reason": self.execution_reason,
            "price_protection_triggered": self.price_protection_triggered,
            "timestamp": self.timestamp,
        }


class ExecutionQualityEngine:
    """Intelligent execution with quality tracking and analytics."""

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self.config = config or ExecutionConfig()
        self._history: list[ExecutionReport] = []
        self._max_history = 1000

    # ------------------------------------------------------------------
    # Order type selection
    # ------------------------------------------------------------------

    def decide_order_type(
        self,
        confidence: float,
        volatility: float | None = None,
        spread_pct: float | None = None,
        is_option: bool = False,
    ) -> str:
        """Decide market vs limit order based on trade characteristics.

        Returns:
            "market" or "limit"
        """
        # Options with wide spreads → always limit
        if is_option and spread_pct and spread_pct > self.config.option_spread_max_pct:
            return "limit"

        # High confidence → limit to get better fill
        if confidence >= self.config.prefer_limit_confidence:
            return "limit"

        # High volatility → market to ensure fill
        if volatility and volatility > 0.03:
            return "market"

        return "market"

    def compute_limit_price(self, side: str, current_price: float) -> float:
        """Compute limit price with small offset for better fills."""
        offset = current_price * self.config.limit_offset_pct
        if side == "buy":
            return round(current_price + offset, 2)  # slightly above for buy
        else:
            return round(current_price - offset, 2)  # slightly below for sell

    # ------------------------------------------------------------------
    # Price protection
    # ------------------------------------------------------------------

    def check_price_protection(
        self, signal_price: float, current_price: float, side: str
    ) -> tuple[bool, str]:
        """Check if price has moved too far since signal generation.

        Returns:
            (is_safe, reason)
        """
        if signal_price <= 0:
            return True, "no_signal_price"

        move_pct = abs(current_price - signal_price) / signal_price
        if move_pct > self.config.price_protection_band_pct:
            direction = "up" if current_price > signal_price else "down"
            reason = f"price_moved_{direction}_{move_pct:.2%}_since_signal"
            return False, reason
        return True, "within_band"

    # ------------------------------------------------------------------
    # Liquidity check
    # ------------------------------------------------------------------

    def check_liquidity(
        self,
        volume: int | None = None,
        bid_ask_spread_pct: float | None = None,
        is_option: bool = False,
    ) -> tuple[bool, list[str]]:
        """Check if instrument has sufficient liquidity.

        Returns:
            (is_liquid, warnings)
        """
        warnings = []

        if volume is not None and volume < self.config.liquidity_min_volume:
            warnings.append(f"low_volume:{volume}<{self.config.liquidity_min_volume}")

        if bid_ask_spread_pct is not None:
            threshold = self.config.option_spread_max_pct if is_option else 0.02
            if bid_ask_spread_pct > threshold:
                warnings.append(f"wide_spread:{bid_ask_spread_pct:.2%}>{threshold:.2%}")

        is_liquid = len(warnings) == 0
        return is_liquid, warnings

    # ------------------------------------------------------------------
    # Execute with quality tracking
    # ------------------------------------------------------------------

    def execute_with_quality(
        self,
        adapter: Any,
        ticker: str,
        side: str,
        quantity: int,
        signal_price: float,
        current_price: float,
        confidence: float = 0.5,
        is_option: bool = False,
        volatility: float | None = None,
        spread_pct: float | None = None,
    ) -> ExecutionReport:
        """Execute an order with full quality tracking.

        Wraps the broker adapter with:
        - Order type selection
        - Price protection
        - Retry logic
        - Slippage measurement
        - Quality scoring
        """
        report = ExecutionReport(
            ticker=ticker,
            side=side,
            quantity=quantity,
            requested_price=current_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Price protection check
        is_safe, reason = self.check_price_protection(signal_price, current_price, side)
        if not is_safe:
            report.price_protection_triggered = True
            report.execution_reason = f"REJECTED: {reason}"
            report.fill_quality = 0.0
            return report

        # Decide order type
        order_type = self.decide_order_type(confidence, volatility, spread_pct, is_option)
        report.order_type_used = order_type

        limit_price = None
        if order_type == "limit":
            limit_price = self.compute_limit_price(side, current_price)

        # Execute with retries
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                start_ms = time.time() * 1000
                intent = {
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "current_price": current_price,
                }
                if limit_price:
                    intent["limit_price"] = limit_price

                result = adapter.place_order(intent)
                end_ms = time.time() * 1000

                filled_price = result.get("filled_price", current_price)
                filled_qty = result.get("filled_quantity", quantity)
                slippage = result.get("slippage", 0)

                report.order_id = result.get("order_id", "")
                report.filled_price = filled_price
                report.filled_quantity = filled_qty
                report.latency_ms = end_ms - start_ms
                report.retries = attempt

                # Calculate slippage
                if side == "buy":
                    report.slippage_pct = (filled_price - current_price) / current_price if current_price > 0 else 0
                else:
                    report.slippage_pct = (current_price - filled_price) / current_price if current_price > 0 else 0
                report.slippage_amount = abs(filled_price - current_price) * filled_qty

                # Partial fill check
                if filled_qty < quantity:
                    report.is_partial = True
                    fill_ratio = filled_qty / quantity
                    if fill_ratio < self.config.partial_fill_min_pct:
                        report.execution_reason = f"partial_fill_too_small:{fill_ratio:.0%}"
                        report.fill_quality = fill_ratio * 0.5
                    else:
                        report.execution_reason = f"partial_fill:{fill_ratio:.0%}"
                        report.fill_quality = fill_ratio

                # Slippage quality
                if abs(report.slippage_pct) <= self.config.max_slippage_pct:
                    slippage_quality = 1.0 - abs(report.slippage_pct) / self.config.max_slippage_pct
                else:
                    slippage_quality = 0.0
                    report.execution_reason += f"|high_slippage:{report.slippage_pct:.4f}"

                # Overall quality = fill ratio * slippage quality * latency factor
                latency_factor = min(1.0, 100.0 / max(report.latency_ms, 1))
                fill_ratio_factor = report.filled_quantity / quantity if quantity > 0 else 0
                report.fill_quality = round(fill_ratio_factor * slippage_quality * latency_factor, 3)

                if not report.execution_reason:
                    report.execution_reason = "filled"

                # Persist report
                self._record_report(report)
                return report

            except Exception as exc:
                last_error = exc
                report.retries = attempt + 1
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))

        report.execution_reason = f"FAILED after {self.config.max_retries} retries: {last_error}"
        report.fill_quality = 0.0
        return report

    def _record_report(self, report: ExecutionReport) -> None:
        self._history.append(report)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Persist to Fill table with quality metrics
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import Fill
            db = SessionLocal()
            try:
                f = Fill(
                    order_id=report.order_id,
                    ticker=report.ticker,
                    side=report.side,
                    quantity=report.filled_quantity,
                    filled_price=report.filled_price,
                    slippage=report.slippage_amount,
                    latency_ms=report.latency_ms,
                    fill_quality=report.fill_quality,
                    partial=report.is_partial,
                )
                db.add(f)
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Fill persistence failed: %s", exc)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return execution quality statistics."""
        if not self._history:
            return {
                "total_executions": 0,
                "avg_slippage_pct": 0,
                "avg_latency_ms": 0,
                "avg_fill_quality": 0,
                "partial_fill_rate": 0,
                "rejection_rate": 0,
            }

        total = len(self._history)
        filled = [r for r in self._history if r.fill_quality > 0]
        partials = [r for r in self._history if r.is_partial]
        rejected = [r for r in self._history if r.price_protection_triggered]

        avg_slippage = sum(abs(r.slippage_pct) for r in filled) / len(filled) if filled else 0
        avg_latency = sum(r.latency_ms for r in filled) / len(filled) if filled else 0
        avg_quality = sum(r.fill_quality for r in filled) / len(filled) if filled else 0

        return {
            "total_executions": total,
            "successful_fills": len(filled),
            "avg_slippage_pct": round(avg_slippage, 4),
            "avg_latency_ms": round(avg_latency, 1),
            "avg_fill_quality": round(avg_quality, 3),
            "partial_fill_rate": round(len(partials) / total, 3) if total else 0,
            "rejection_rate": round(len(rejected) / total, 3) if total else 0,
            "limit_order_pct": round(
                sum(1 for r in self._history if r.order_type_used == "limit") / total, 3
            ) if total else 0,
        }

    def get_recent_reports(self, limit: int = 20) -> list[dict]:
        return [r.to_dict() for r in self._history[-limit:]]


_execution_engine: ExecutionQualityEngine | None = None


def get_execution_engine() -> ExecutionQualityEngine:
    """Module-level singleton accessor."""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionQualityEngine()
    return _execution_engine
