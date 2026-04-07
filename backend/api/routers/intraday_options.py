"""Options / F&O signal router – generates derivatives trading signals."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.intraday.options_engine import (
    FnOConfig,
    OptionChainSnapshot,
    OptionSignalEngine,
)
from backend.intraday.schemas import OptionSignalRequest, OptionSignalResponse
from backend.services.monitoring import record_intraday_option_signal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intraday/options", tags=["intraday-options"])

_engine = OptionSignalEngine()


@router.post("/signal", response_model=OptionSignalResponse)
async def generate_option_signal(req: OptionSignalRequest):
    """Generate an F&O signal from underlying analysis."""
    chain = OptionChainSnapshot(
        symbol=req.symbol,
        underlying_price=req.underlying_price,
        atm_iv=req.atm_iv,
        put_call_ratio=req.put_call_ratio,
        days_to_expiry=req.days_to_expiry,
    )

    signal = _engine.generate_signal(
        underlying_trend=req.underlying_trend,
        trend_confidence=req.trend_confidence,
        chain=chain,
    )

    record_intraday_option_signal(signal.signal_type.value)

    return OptionSignalResponse(
        symbol=signal.symbol,
        signal_type=signal.signal_type.value,
        direction=signal.direction,
        confidence=signal.confidence,
        underlying_price=signal.underlying_price,
        entry_strike=signal.entry_strike,
        exit_strike=signal.exit_strike,
        option_type=signal.option_type,
        expiry=signal.expiry,
        max_loss=round(signal.max_loss, 2),
        max_profit=round(signal.max_profit, 2),
        breakeven=round(signal.breakeven, 2),
        risk_reward=round(signal.risk_reward, 2),
        volatility_regime=signal.volatility_regime,
        reasoning=signal.reasoning,
        eligible=signal.eligible,
        rejection_reason=signal.rejection_reason,
    )


@router.post("/batch")
async def generate_batch_signals(requests: list[OptionSignalRequest]):
    """Generate F&O signals for multiple underlyings."""
    results = []
    for req in requests:
        chain = OptionChainSnapshot(
            symbol=req.symbol,
            underlying_price=req.underlying_price,
            atm_iv=req.atm_iv,
            put_call_ratio=req.put_call_ratio,
            days_to_expiry=req.days_to_expiry,
        )
        signal = _engine.generate_signal(
            underlying_trend=req.underlying_trend,
            trend_confidence=req.trend_confidence,
            chain=chain,
        )
        results.append(OptionSignalResponse(
            symbol=signal.symbol,
            signal_type=signal.signal_type.value,
            direction=signal.direction,
            confidence=signal.confidence,
            underlying_price=signal.underlying_price,
            entry_strike=signal.entry_strike,
            exit_strike=signal.exit_strike,
            option_type=signal.option_type,
            expiry=signal.expiry,
            max_loss=round(signal.max_loss, 2),
            max_profit=round(signal.max_profit, 2),
            breakeven=round(signal.breakeven, 2),
            risk_reward=round(signal.risk_reward, 2),
            volatility_regime=signal.volatility_regime,
            reasoning=signal.reasoning,
            eligible=signal.eligible,
            rejection_reason=signal.rejection_reason,
        ))
    return {"signals": results}


@router.get("/health")
async def health():
    return {"status": "ok", "service": "intraday-options"}
