"""Options strategy builder API endpoints."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math

from fastapi import APIRouter

from backend.services.options_strategy import OptionsStrategyEngine

router = APIRouter(tags=["options-strategy"])


def _as_mapping(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if is_dataclass(obj):
        return asdict(obj)
    return getattr(obj, "__dict__", {}) or {}


def _num(value, default=0.0):
    try:
        out = float(value)
        if not math.isfinite(out):
            return float(default)
        return out
    except (TypeError, ValueError):
        return float(default)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _format_strike(value) -> str:
    n = _num(value, 0.0)
    return str(int(n)) if float(n).is_integer() else str(round(n, 2))


def _build_leg_instrument(rec, leg_data: dict, idx: int) -> str:
    instrument = str(leg_data.get("instrument") or "").strip()
    if instrument:
        return instrument
    underlying = str(getattr(rec, "underlying", "") or "").strip() or "OPT"
    option_type = str(leg_data.get("option_type") or "CE").upper()
    strike = _format_strike(leg_data.get("strike"))
    expiry = str(leg_data.get("expiry") or "").strip()
    if expiry:
        return f"{underlying}-{expiry}-{strike}-{option_type}"
    return f"{underlying}-{strike}-{option_type}-L{idx + 1}"


def _serialize(rec):
    """Serialize a StrategyRecommendation to dict."""
    legs_payload = []
    for idx, leg in enumerate(getattr(rec, "legs", []) or []):
        data = _as_mapping(leg)
        legs_payload.append(
            {
                "instrument": _build_leg_instrument(rec, data, idx),
                "option_type": str(data.get("option_type") or "CE").upper(),
                "strike": _num(data.get("strike"), 0.0),
                "expiry": str(data.get("expiry") or ""),
                "side": str(data.get("side") or "buy").lower(),
                "quantity": _int(data.get("quantity"), 1),
                "premium": _num(data.get("premium"), 0.0),
            }
        )

    breakeven = getattr(rec, "breakeven", None)
    if not breakeven:
        breakeven = getattr(rec, "breakeven_points", []) or []
    rationale = getattr(rec, "rationale", None) or getattr(rec, "explanation", "") or ""

    return {
        "strategy_type": rec.strategy_type.value if hasattr(rec.strategy_type, "value") else str(rec.strategy_type),
        "underlying": getattr(rec, "underlying", ""),
        "legs": legs_payload,
        "max_profit": _num(getattr(rec, "max_profit", 0.0), 0.0),
        "max_loss": _num(getattr(rec, "max_loss", 0.0), 0.0),
        "breakeven": [_num(x, 0.0) for x in breakeven],
        "margin_required": _num(getattr(rec, "margin_required", 0.0), 0.0),
        "rationale": str(rationale),
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
            option_type=l.get("option_type", "CE"),
            strike=float(l["strike"]),
            expiry=l.get("expiry", ""),
            side=l.get("side", "buy"),
            quantity=int(l.get("quantity", 1)),
            premium=float(l.get("premium", 0)),
            iv=float(l.get("iv", 0)),
        )
        for l in payload.get("legs", [])
    ]
    spot_range = payload.get("spot_range")
    if spot_range:
        spot_range = (float(spot_range[0]), float(spot_range[1]))
    points = int(payload.get("points", 100))
    points_data = OptionsStrategyEngine.compute_payoff(legs, spot_range, points)
    # Frontend expects both `pnl` and `payoff` keys; keep both for compatibility.
    return [
        {
            "spot": _num(row.get("spot"), 0.0),
            "pnl": _num(row.get("pnl", row.get("payoff")), 0.0),
            "payoff": _num(row.get("payoff", row.get("pnl")), 0.0),
        }
        for row in points_data
    ]
