"""Event features — structured event risk signals for the model.

Queries active events from the DB and converts them to numeric features.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


async def get_event_feature_vector() -> dict[str, float]:
    """Build a feature vector from currently active events.

    Returns a flat dict of event-related features.
    """
    from app.ingestion.event_ingestion import get_active_events

    events = await get_active_events()

    if not events:
        return _empty_event_features()

    severities = [e["severity"] for e in events]
    vol_shocks = [e["volatility_shock_score"] for e in events]
    sent_impacts = [e["sentiment_impact_score"] for e in events]
    gap_risks = [e["gap_risk_score"] for e in events]

    # Decay weighting by recency
    now = datetime.now(timezone.utc)
    weighted_severity = 0.0
    for e in events:
        ts = e.get("timestamp")
        if ts:
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            age_hours = max((now - ts).total_seconds() / 3600, 1)
            decay = np.exp(-0.05 * age_hours)
            weighted_severity += e["severity"] * decay

    return {
        "event_count": float(len(events)),
        "event_max_severity": max(severities),
        "event_avg_severity": np.mean(severities),
        "event_weighted_severity": round(weighted_severity, 4),
        "event_max_vol_shock": max(vol_shocks),
        "event_avg_vol_shock": np.mean(vol_shocks),
        "event_max_sent_impact": min(sent_impacts),  # most negative
        "event_avg_sent_impact": np.mean(sent_impacts),
        "event_max_gap_risk": max(gap_risks),
        "event_avg_gap_risk": np.mean(gap_risks),
    }


def _empty_event_features() -> dict[str, float]:
    keys = [
        "event_count", "event_max_severity", "event_avg_severity",
        "event_weighted_severity", "event_max_vol_shock", "event_avg_vol_shock",
        "event_max_sent_impact", "event_avg_sent_impact",
        "event_max_gap_risk", "event_avg_gap_risk",
    ]
    return {k: 0.0 for k in keys}


def event_features_to_series() -> pd.Series:
    """Synchronous wrapper for convenience (runs the coroutine)."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an async context — return empty and let caller await
        return pd.Series(_empty_event_features())

    return pd.Series(asyncio.run(get_event_feature_vector()))
