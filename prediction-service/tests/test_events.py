"""Tests for event ingestion and scoring."""

import pytest

from app.ingestion.event_ingestion import (
    score_event,
    EventInput,
    EventType,
)


def test_war_event_high_severity():
    event = EventInput(event_type=EventType.WAR, headline="India-Pakistan border tensions escalate")
    scored = score_event(event)
    assert scored.severity > 0.8
    assert "DEFENSE" in scored.sectors_impacted
    assert scored.volatility_shock_score > 0.5


def test_earnings_event_low_severity():
    event = EventInput(event_type=EventType.EARNINGS, headline="Reliance Q3 results", region="India")
    scored = score_event(event)
    assert scored.severity < 0.5


def test_non_india_region_lower_impact():
    event_india = EventInput(event_type=EventType.GEOPOLITICAL, headline="Test event", region="India")
    event_eu = EventInput(event_type=EventType.GEOPOLITICAL, headline="Test event", region="Europe")
    scored_india = score_event(event_india)
    scored_eu = score_event(event_eu)
    assert scored_india.severity > scored_eu.severity


def test_severity_override():
    event = EventInput(
        event_type=EventType.OTHER,
        headline="Custom event",
        severity_override=0.95,
    )
    scored = score_event(event)
    assert scored.severity >= 0.76  # 0.95 * region_mult capped at 1.0
