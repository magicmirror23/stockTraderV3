"""Market session, regime, events, and drift routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ingestion.event_ingestion import EventInput, EventType

router = APIRouter(tags=["market"])


# ── Market Session ───────────────────────────────────────────────────

@router.get("/market-session")
async def market_session():
    """Get current NSE market session state."""
    from app.services.market_session import get_session_state

    return get_session_state()


# ── Regime ───────────────────────────────────────────────────────────

@router.get("/regime/current")
async def current_regime():
    """Get the current market regime classification."""
    return {
        "regime": "unknown",
        "confidence": 0.0,
        "message": "Regime model must be trained first",
    }


# ── Events ───────────────────────────────────────────────────────────

class EventRequest(BaseModel):
    event_type: str = Field(..., description="Event type: war, geopolitical, election, etc.")
    headline: str = Field(..., description="Event headline/description")
    region: str = "India"
    severity_override: float | None = None
    source: str = "api"


@router.get("/events/active")
async def active_events():
    """List currently active events."""
    from app.ingestion.event_ingestion import get_active_events

    events = await get_active_events()
    return {"events": events, "count": len(events)}


@router.post("/events/ingest")
async def ingest_event(req: EventRequest):
    """Ingest and score a new event."""
    from app.ingestion.event_ingestion import ingest_event, EventInput, EventType

    try:
        etype = EventType(req.event_type)
    except ValueError:
        etype = EventType.OTHER

    event = EventInput(
        event_type=etype,
        headline=req.headline,
        region=req.region,
        severity_override=req.severity_override,
        source=req.source,
    )
    scored = await ingest_event(event)
    return {
        "status": "ingested",
        "event_type": scored.event_type,
        "severity": scored.severity,
        "volatility_shock_score": scored.volatility_shock_score,
    }


# ── Drift ────────────────────────────────────────────────────────────

@router.get("/drift")
async def drift_report():
    """Run drift detection and return report."""
    from app.monitoring.drift import run_drift_check

    report = await run_drift_check()
    return report
