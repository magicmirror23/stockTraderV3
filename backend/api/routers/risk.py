"""Advanced risk management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["risk"])


def _engine():
    from backend.services.advanced_risk import get_risk_engine
    return get_risk_engine()


@router.get("/risk/status")
async def risk_status():
    """Current risk engine status: capital, exposure, daily P&L, circuit breaker."""
    return _engine().status


@router.get("/risk/exposure/sector")
async def sector_exposure():
    """Current sector exposure percentages."""
    return _engine().sector_exposure()


@router.get("/risk/exposure/instrument")
async def instrument_exposure():
    """Current instrument-type exposure percentages."""
    return _engine().instrument_exposure()


@router.get("/risk/exposure/strategy")
async def strategy_exposure():
    """Current strategy-type exposure percentages."""
    return _engine().strategy_exposure()


@router.get("/risk/greeks")
async def portfolio_greeks():
    """Aggregate portfolio Greeks (delta, gamma, theta, vega)."""
    return _engine().portfolio_greeks()


@router.post("/risk/approve")
async def approve_trade(payload: dict):
    """Run 12-point risk approval for a proposed trade.

    Body: {ticker, side, price, quantity, instrument_type, expected_return,
           confidence, volatility, greeks?}
    """
    required = ["ticker", "side", "price", "quantity"]
    for k in required:
        if k not in payload:
            raise HTTPException(400, f"Missing required field: {k}")

    approval = _engine().approve_trade(
        ticker=payload["ticker"],
        side=payload["side"],
        price=float(payload["price"]),
        quantity=int(payload["quantity"]),
        instrument_type=payload.get("instrument_type", "equity"),
        expected_return=float(payload.get("expected_return", 0)),
        confidence=float(payload.get("confidence", 0.5)),
        volatility=float(payload.get("volatility", 0.02)),
        greeks=payload.get("greeks"),
    )
    return {
        "approved": approval.approved,
        "reasons": approval.reasons,
        "adjusted_quantity": approval.adjusted_quantity,
        "risk_score": approval.risk_score,
    }


@router.post("/risk/sizing/kelly")
async def kelly_sizing(payload: dict):
    """Kelly criterion position sizing.

    Body: {win_rate, avg_win, avg_loss}
    """
    return {
        "fraction": _engine().kelly_sizing(
            win_rate=float(payload["win_rate"]),
            avg_win=float(payload["avg_win"]),
            avg_loss=float(payload["avg_loss"]),
        )
    }


@router.post("/risk/sizing/volatility")
async def volatility_sizing(payload: dict):
    """ATR-based volatility-adjusted position sizing.

    Body: {price, atr, target_risk_pct?}
    """
    return {
        "quantity": _engine().volatility_adjusted_size(
            price=float(payload["price"]),
            atr=float(payload["atr"]),
            target_risk_pct=float(payload.get("target_risk_pct", 0.01)),
        )
    }


@router.get("/risk/snapshot")
async def risk_snapshots(limit: int = 20):
    """Recent risk snapshots from the database."""
    try:
        from backend.db.session import SessionLocal
        from backend.db.models import RiskSnapshot

        db = SessionLocal()
        try:
            rows = (
                db.query(RiskSnapshot)
                .order_by(RiskSnapshot.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": str(r.id),
                    "snapshot_type": r.snapshot_type,
                    "data": r.data,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                }
                for r in rows
            ]
        finally:
            db.close()
    except Exception as exc:
        return {"error": str(exc)}
