"""Strategy intelligence layer — meta-strategy selection based on regime,
confidence, liquidity, and risk budget.

Selects from: momentum, mean_reversion, breakout, trend_following,
options_income, options_volatility, or no_trade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StrategyDecision:
    """Outcome of the strategy selector."""
    strategy: str  # momentum|mean_reversion|breakout|trend_following|options_income|options_volatility|no_trade
    confidence: float
    reasons: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    fallback_to_no_trade: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "confidence": round(self.confidence, 3),
            "reasons": self.reasons,
            "parameters": self.parameters,
            "fallback_to_no_trade": self.fallback_to_no_trade,
            "timestamp": self.timestamp,
        }


class StrategyIntelligence:
    """Meta-strategy selector that picks the right approach per symbol/regime.

    Uses:
    - Market regime from RegimeDetector
    - Model confidence from prediction
    - Liquidity indicators
    - Available risk budget from AdvancedRiskEngine
    - Options IV surface (if available)
    """

    def __init__(
        self,
        min_confidence_equity: float = 0.6,
        min_confidence_options: float = 0.65,
        min_edge_threshold: float = 0.01,
    ) -> None:
        self.min_confidence_equity = min_confidence_equity
        self.min_confidence_options = min_confidence_options
        self.min_edge_threshold = min_edge_threshold
        self._history: list[StrategyDecision] = []

    def select(
        self,
        ticker: str,
        prediction: dict,
        regime: dict | None = None,
        risk_budget: float | None = None,
        is_option_eligible: bool = True,
        iv_percentile: float | None = None,
        liquidity_ok: bool = True,
    ) -> StrategyDecision:
        """Select optimal strategy for a ticker.

        Args:
            ticker: symbol
            prediction: dict with action, confidence, expected_return
            regime: dict from RegimeDetector with regime, volatility, trend_strength
            risk_budget: available risk budget (₹)
            is_option_eligible: whether options are available for this ticker
            iv_percentile: IV rank (0-100) if available
            liquidity_ok: whether the instrument has sufficient liquidity

        Returns:
            StrategyDecision
        """
        decision = StrategyDecision(
            strategy="no_trade",
            confidence=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        action = prediction.get("action", "hold")
        confidence = prediction.get("confidence", 0)
        expected_return = prediction.get("expected_return", 0)
        regime_data = regime or {}
        regime_type = regime_data.get("regime", "unknown")
        volatility = regime_data.get("volatility", 0.2)
        trend = regime_data.get("trend_strength", 0)

        reasons = []

        # Gate: No trade if action is hold
        if action == "hold":
            decision.reasons = ["signal_is_hold"]
            decision.fallback_to_no_trade = True
            self._record(decision)
            return decision

        # Gate: Insufficient confidence
        if confidence < self.min_confidence_equity:
            decision.reasons = [f"low_confidence:{confidence:.2f}<{self.min_confidence_equity}"]
            decision.fallback_to_no_trade = True
            self._record(decision)
            return decision

        # Gate: Liquidity
        if not liquidity_ok:
            decision.reasons = ["insufficient_liquidity"]
            decision.fallback_to_no_trade = True
            self._record(decision)
            return decision

        # Gate: Risk budget
        if risk_budget is not None and risk_budget < 1000:
            decision.reasons = [f"risk_budget_exhausted:{risk_budget:.0f}"]
            decision.fallback_to_no_trade = True
            self._record(decision)
            return decision

        # Gate: Edge too small
        if abs(expected_return) < self.min_edge_threshold:
            decision.reasons = [f"edge_too_small:{expected_return:.4f}"]
            decision.fallback_to_no_trade = True
            self._record(decision)
            return decision

        # --- Strategy Selection by Regime ---

        if regime_type in ("trending_up", "trending_down"):
            if confidence >= 0.75 and abs(trend) > 0.03:
                decision.strategy = "trend_following"
                reasons.append(f"strong_trend:{trend:.3f}")
            else:
                decision.strategy = "momentum"
                reasons.append(f"moderate_trend:{trend:.3f}")
            decision.confidence = confidence
            decision.parameters = {
                "side": action,
                "trailing_stop": True,
                "hold_period": "intraday" if volatility > 0.25 else "swing",
            }

        elif regime_type == "range_bound":
            decision.strategy = "mean_reversion"
            decision.confidence = confidence * 0.9  # slight discount for mean reversion
            reasons.append("range_bound_regime")
            decision.parameters = {
                "side": action,
                "target_pct": 0.02,
                "tight_stop": True,
            }

        elif regime_type == "high_vol":
            if is_option_eligible and iv_percentile and iv_percentile > 70:
                decision.strategy = "options_income"
                reasons.append(f"high_iv_percentile:{iv_percentile:.0f}")
                decision.confidence = min(confidence, 0.75)
                decision.parameters = {
                    "preferred_strategy": "iron_condor" if abs(trend) < 0.01 else "credit_spread",
                    "iv_percentile": iv_percentile,
                }
            elif is_option_eligible and iv_percentile and iv_percentile < 30:
                decision.strategy = "options_volatility"
                reasons.append(f"low_iv_buy_vol:{iv_percentile:.0f}")
                decision.confidence = min(confidence, 0.7)
                decision.parameters = {
                    "preferred_strategy": "long_straddle",
                    "iv_percentile": iv_percentile,
                }
            else:
                decision.strategy = "momentum"
                decision.confidence = confidence * 0.8
                reasons.append("high_vol_equity_momentum")
                decision.parameters = {
                    "side": action,
                    "tight_stop": True,
                    "reduced_size": True,
                }

        elif regime_type == "low_vol":
            if is_option_eligible and iv_percentile and iv_percentile < 20:
                decision.strategy = "options_volatility"
                reasons.append("low_vol_long_gamma")
                decision.confidence = min(confidence, 0.65)
                decision.parameters = {"preferred_strategy": "long_straddle"}
            else:
                decision.strategy = "breakout"
                reasons.append("low_vol_breakout_candidate")
                decision.confidence = confidence * 0.85
                decision.parameters = {
                    "side": action,
                    "breakout_confirmation": True,
                }

        elif regime_type in ("gap_up", "gap_down"):
            decision.strategy = "momentum"
            reasons.append(f"gap_{regime_type}")
            decision.confidence = confidence * 0.85
            decision.parameters = {
                "side": action,
                "fade_gap": regime_type != action.replace("buy", "gap_up").replace("sell", "gap_down"),
            }

        elif regime_type == "crash":
            # Extremely cautious
            decision.strategy = "no_trade"
            decision.fallback_to_no_trade = True
            reasons.append("crash_regime_no_trade")
            decision.confidence = 0
            self._record(decision)
            return decision

        else:
            # Unknown regime → momentum default
            decision.strategy = "momentum"
            decision.confidence = confidence * 0.7
            reasons.append("unknown_regime_default_momentum")
            decision.parameters = {"side": action}

        decision.reasons = reasons
        self._record(decision)
        return decision

    def _record(self, decision: StrategyDecision) -> None:
        self._history.append(decision)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        # Emit event
        try:
            from backend.services.event_bus import get_event_bus, Event, EventType
            et = EventType.STRATEGY_SELECTED if decision.strategy != "no_trade" else EventType.STRATEGY_SKIP
            get_event_bus().publish(Event(
                et, decision.to_dict(), source="strategy_intelligence",
            ))
        except Exception:
            pass

    def get_recent_decisions(self, limit: int = 20) -> list[dict]:
        return [d.to_dict() for d in self._history[-limit:]]

    def get_stats(self) -> dict:
        if not self._history:
            return {"total": 0}
        total = len(self._history)
        by_strategy: dict[str, int] = {}
        no_trade_count = 0
        for d in self._history:
            by_strategy[d.strategy] = by_strategy.get(d.strategy, 0) + 1
            if d.fallback_to_no_trade:
                no_trade_count += 1
        return {
            "total_decisions": total,
            "by_strategy": by_strategy,
            "no_trade_rate": round(no_trade_count / total, 3) if total else 0,
            "avg_confidence": round(
                sum(d.confidence for d in self._history) / total, 3
            ) if total else 0,
        }


_strategy_intelligence: StrategyIntelligence | None = None


def get_strategy_intelligence() -> StrategyIntelligence:
    """Module-level singleton accessor."""
    global _strategy_intelligence
    if _strategy_intelligence is None:
        _strategy_intelligence = StrategyIntelligence()
    return _strategy_intelligence
