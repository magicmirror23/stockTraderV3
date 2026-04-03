"""Options strategy builder API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.services.options_strategy import OptionsStrategyEngine

router = APIRouter(tags=["options-strategy"])


def _serialize(rec):
    """Serialize a StrategyRecommendation to dict."""
    return {
        "strategy_type": rec.strategy_type.value if hasattr(rec.strategy_type, "value") else str(rec.strategy_type),
        "legs": [
            {
                "instrument": l.instrument,
                "option_type": l.option_type,
                "strike": l.strike,
                "expiry": l.expiry,
                "side": l.side,
                "quantity": l.quantity,
                "premium": l.premium,
            }
            for l in rec.legs
        ],
        "max_profit": rec.max_profit,
        "max_loss": rec.max_loss,
        "breakeven": rec.breakeven,
        "margin_required": rec.margin_required,
        "rationale": rec.rationale,
    }


@router.post("/options/recommend")
async def recommend_strategy(payload: dict):
    """Recommend an options strategy based on market view.

    Body: {underlying, spot, expiry, direction, confidence,
           regime?, iv_percentile?, iv?, lot_size?}
    """
    rec = OptionsStrategyEngine.recommend_strategy(
        underlying=payload["underlying"],
        spot=float(payload["spot"]),
        expiry=payload["expiry"],
        direction=payload.get("direction", "bullish"),
        confidence=float(payload.get("confidence", 0.6)),
        regime=payload.get("regime", "range_bound"),
        iv_percentile=float(payload.get("iv_percentile", 0.5)),
        iv=float(payload.get("iv", 0.2)),
        lot_size=int(payload.get("lot_size", 50)),
    )
    return _serialize(rec)


@router.post("/options/covered-call")
async def build_covered_call(payload: dict):
    """Build a covered call strategy."""
    rec = OptionsStrategyEngine.build_covered_call(
        underlying=payload["underlying"],
        spot=float(payload["spot"]),
        expiry=payload["expiry"],
        iv=float(payload.get("iv", 0.2)),
        lot_size=int(payload.get("lot_size", 50)),
    )
    return _serialize(rec)


@router.post("/options/bull-call-spread")
async def build_bull_call_spread(payload: dict):
    """Build a bull call spread strategy."""
    rec = OptionsStrategyEngine.build_bull_call_spread(
        underlying=payload["underlying"],
        spot=float(payload["spot"]),
        expiry=payload["expiry"],
        iv=float(payload.get("iv", 0.2)),
        lot_size=int(payload.get("lot_size", 50)),
    )
    return _serialize(rec)


@router.post("/options/iron-condor")
async def build_iron_condor(payload: dict):
    """Build an iron condor strategy."""
    rec = OptionsStrategyEngine.build_iron_condor(
        underlying=payload["underlying"],
        spot=float(payload["spot"]),
        expiry=payload["expiry"],
        iv=float(payload.get("iv", 0.2)),
        lot_size=int(payload.get("lot_size", 50)),
    )
    return _serialize(rec)


@router.post("/options/straddle")
async def build_straddle(payload: dict):
    """Build a long straddle strategy."""
    rec = OptionsStrategyEngine.build_long_straddle(
        underlying=payload["underlying"],
        spot=float(payload["spot"]),
        expiry=payload["expiry"],
        iv=float(payload.get("iv", 0.2)),
        lot_size=int(payload.get("lot_size", 50)),
    )
    return _serialize(rec)


@router.post("/options/payoff")
async def compute_payoff(payload: dict):
    """Compute payoff diagram data for given option legs.

    Body: {legs: list[dict], spot_range?: [low, high], points?: int}
    """
    from backend.services.options_strategy import OptionLeg

    legs = [
        OptionLeg(
            instrument=l["instrument"],
            option_type=l.get("option_type", "CE"),
            strike=float(l["strike"]),
            expiry=l.get("expiry", ""),
            side=l.get("side", "buy"),
            quantity=int(l.get("quantity", 1)),
            premium=float(l.get("premium", 0)),
        )
        for l in payload.get("legs", [])
    ]
    spot_range = payload.get("spot_range")
    if spot_range:
        spot_range = (float(spot_range[0]), float(spot_range[1]))
    points = int(payload.get("points", 100))
    return OptionsStrategyEngine.compute_payoff(legs, spot_range, points)
