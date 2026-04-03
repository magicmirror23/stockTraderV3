"""Event ingestion pipeline — multi-factor severity scoring for events.

Events are scored across five orthogonal dimensions (volatility shock,
sentiment impact, gap risk, liquidity impact, contagion risk), then
combined into a composite severity.  Scores decay with time and adjust
for region proximity and sector relevance.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    WAR = "war"
    GEOPOLITICAL = "geopolitical"
    ELECTION = "election"
    POLICY = "policy"
    NATURAL_DISASTER = "natural_disaster"
    PANDEMIC = "pandemic"
    REGULATORY = "regulatory"
    EARNINGS = "earnings"
    CENTRAL_BANK = "central_bank"
    TRADE_WAR = "trade_war"
    SANCTIONS = "sanctions"
    OTHER = "other"


# Sector impact mapping for common event types
SECTOR_IMPACT: dict[EventType, list[str]] = {
    EventType.WAR: ["DEFENSE", "OIL", "GOLD", "BANKING"],
    EventType.GEOPOLITICAL: ["IT", "BANKING", "OIL"],
    EventType.ELECTION: ["INFRA", "BANKING", "PSU"],
    EventType.POLICY: ["BANKING", "AUTO", "PHARMA"],
    EventType.PANDEMIC: ["PHARMA", "IT", "FMCG"],
    EventType.CENTRAL_BANK: ["BANKING", "NBFC", "REALTY"],
    EventType.TRADE_WAR: ["IT", "METAL", "AUTO"],
    EventType.SANCTIONS: ["IT", "OIL", "BANKING", "PHARMA"],
    EventType.NATURAL_DISASTER: ["INFRA", "INSURANCE", "REALTY"],
    EventType.REGULATORY: ["BANKING", "NBFC", "PHARMA", "IT"],
}

# Multi-dimensional base scores per event type.
# Keys: vol_shock, sent_impact, gap_risk, liquidity_impact, contagion
_EVENT_PROFILES: dict[EventType, dict[str, float]] = {
    EventType.WAR:              {"sev": 0.90, "vol": 0.90, "sent": -0.85, "gap": 0.80, "liq": 0.70, "cont": 0.80},
    EventType.GEOPOLITICAL:     {"sev": 0.70, "vol": 0.60, "sent": -0.55, "gap": 0.40, "liq": 0.30, "cont": 0.50},
    EventType.ELECTION:         {"sev": 0.50, "vol": 0.45, "sent": -0.20, "gap": 0.35, "liq": 0.20, "cont": 0.30},
    EventType.POLICY:           {"sev": 0.40, "vol": 0.35, "sent": -0.25, "gap": 0.20, "liq": 0.15, "cont": 0.20},
    EventType.NATURAL_DISASTER: {"sev": 0.60, "vol": 0.55, "sent": -0.50, "gap": 0.30, "liq": 0.40, "cont": 0.25},
    EventType.PANDEMIC:         {"sev": 0.85, "vol": 0.80, "sent": -0.75, "gap": 0.60, "liq": 0.80, "cont": 0.90},
    EventType.REGULATORY:       {"sev": 0.30, "vol": 0.25, "sent": -0.20, "gap": 0.10, "liq": 0.10, "cont": 0.15},
    EventType.EARNINGS:         {"sev": 0.20, "vol": 0.20, "sent": -0.10, "gap": 0.15, "liq": 0.05, "cont": 0.05},
    EventType.CENTRAL_BANK:     {"sev": 0.60, "vol": 0.55, "sent": -0.40, "gap": 0.35, "liq": 0.30, "cont": 0.45},
    EventType.TRADE_WAR:        {"sev": 0.65, "vol": 0.55, "sent": -0.50, "gap": 0.30, "liq": 0.35, "cont": 0.60},
    EventType.SANCTIONS:        {"sev": 0.70, "vol": 0.60, "sent": -0.55, "gap": 0.35, "liq": 0.45, "cont": 0.65},
    EventType.OTHER:            {"sev": 0.20, "vol": 0.15, "sent": -0.10, "gap": 0.05, "liq": 0.05, "cont": 0.05},
}

# Region proximity weights (closer regions → larger impact on NSE)
_REGION_WEIGHTS: dict[str, float] = {
    "india": 1.0,
    "asia": 0.85,
    "middle east": 0.75,
    "europe": 0.60,
    "us": 0.65,
    "americas": 0.55,
    "africa": 0.45,
    "global": 0.90,
}

# Expected duration (hours) by event type
_DURATION_MAP: dict[EventType, float] = {
    EventType.WAR: 336,
    EventType.PANDEMIC: 1440,
    EventType.ELECTION: 72,
    EventType.CENTRAL_BANK: 48,
    EventType.EARNINGS: 24,
    EventType.GEOPOLITICAL: 120,
    EventType.POLICY: 72,
    EventType.REGULATORY: 168,
    EventType.TRADE_WAR: 240,
    EventType.SANCTIONS: 336,
    EventType.NATURAL_DISASTER: 96,
}


@dataclass
class EventInput:
    """Raw event input for scoring."""
    event_type: EventType
    headline: str
    region: str = "India"
    severity_override: float | None = None
    source: str = "manual"
    affected_sectors: list[str] | None = None


@dataclass
class ScoredEvent:
    """Multi-dimensional scored event ready for DB insertion."""
    event_type: str
    severity: float
    region: str
    sectors_impacted: list[str]
    confidence: float
    volatility_shock_score: float
    sentiment_impact_score: float
    gap_risk_score: float
    liquidity_impact_score: float
    contagion_risk_score: float
    expected_duration_hours: float
    source: str
    raw_text: str


def score_event(event: EventInput) -> ScoredEvent:
    """Score a single event using multi-factor heuristics.

    Scoring pipeline:
      1. Look up base profile for the event type.
      2. Apply region proximity multiplier.
      3. Apply compound severity boost when multiple risk axes are high.
      4. Clamp all scores to [0, 1] (sentiment to [-1, 0]).
    """
    etype = event.event_type
    profile = _EVENT_PROFILES.get(etype, _EVENT_PROFILES[EventType.OTHER])

    region_key = event.region.lower()
    region_mult = _REGION_WEIGHTS.get(region_key, 0.50)

    base_sev = event.severity_override if event.severity_override is not None else profile["sev"]
    severity = min(base_sev * region_mult, 1.0)

    vol_shock = min(profile["vol"] * region_mult, 1.0)
    sent_impact = max(profile["sent"] * region_mult, -1.0)
    gap_risk = min(profile["gap"] * region_mult, 1.0) if severity > 0.35 else profile["gap"] * 0.3
    liq_impact = min(profile["liq"] * region_mult, 1.0)
    contagion = min(profile["cont"] * region_mult, 1.0)

    # Compound boost: when >=3 axes are elevated, boost overall severity
    elevated = sum(1 for v in [vol_shock, abs(sent_impact), gap_risk, liq_impact, contagion] if v > 0.50)
    if elevated >= 3:
        severity = min(severity * 1.15, 1.0)

    sectors = event.affected_sectors or SECTOR_IMPACT.get(etype, [])
    duration = _DURATION_MAP.get(etype, 48)

    return ScoredEvent(
        event_type=etype.value,
        severity=round(severity, 4),
        region=event.region,
        sectors_impacted=sectors,
        confidence=round(0.5 + 0.1 * elevated, 2),
        volatility_shock_score=round(vol_shock, 4),
        sentiment_impact_score=round(sent_impact, 4),
        gap_risk_score=round(gap_risk, 4),
        liquidity_impact_score=round(liq_impact, 4),
        contagion_risk_score=round(contagion, 4),
        expected_duration_hours=float(duration),
        source=event.source,
        raw_text=event.headline,
    )


async def ingest_event(event: EventInput) -> ScoredEvent:
    """Score and persist an event."""
    from app.db.session import async_session_factory
    from app.db.models import EventScore

    scored = score_event(event)

    async with async_session_factory() as session:
        record = EventScore(
            event_type=scored.event_type,
            severity=scored.severity,
            region=scored.region,
            sectors_impacted=scored.sectors_impacted,
            confidence=scored.confidence,
            volatility_shock_score=scored.volatility_shock_score,
            sentiment_impact_score=scored.sentiment_impact_score,
            gap_risk_score=scored.gap_risk_score,
            expected_duration_hours=scored.expected_duration_hours,
            source=scored.source,
            raw_text=scored.raw_text,
            is_active=True,
        )
        session.add(record)
        await session.commit()

    logger.info(
        "Ingested event: %s severity=%.2f vol=%.2f sent=%.2f gap=%.2f liq=%.2f cont=%.2f",
        scored.event_type, scored.severity,
        scored.volatility_shock_score, scored.sentiment_impact_score,
        scored.gap_risk_score, scored.liquidity_impact_score,
        scored.contagion_risk_score,
    )
    return scored


async def get_active_events() -> list[dict]:
    """Return currently active events from DB, auto-deactivating expired ones."""
    from sqlalchemy import select, update
    from app.db.session import async_session_factory
    from app.db.models import EventScore

    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        stmt = select(EventScore).where(EventScore.is_active == True).order_by(  # noqa: E712
            EventScore.timestamp.desc()
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        active: list[dict] = []
        expired_ids: list[int] = []
        for r in rows:
            # Auto-expire events past their expected duration
            if r.timestamp and r.expected_duration_hours:
                age_hours = (now - r.timestamp).total_seconds() / 3600
                if age_hours > r.expected_duration_hours:
                    expired_ids.append(r.id)
                    continue

            active.append({
                "event_type": r.event_type,
                "severity": r.severity,
                "region": r.region,
                "sectors_impacted": r.sectors_impacted,
                "volatility_shock_score": r.volatility_shock_score,
                "sentiment_impact_score": r.sentiment_impact_score,
                "gap_risk_score": r.gap_risk_score,
                "is_active": r.is_active,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "expected_duration_hours": r.expected_duration_hours,
            })

        # Bulk-deactivate expired
        if expired_ids:
            await session.execute(
                update(EventScore).where(EventScore.id.in_(expired_ids)).values(is_active=False)
            )
            await session.commit()
            logger.info("Auto-deactivated %d expired events", len(expired_ids))

        return active
