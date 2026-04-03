"""Tests for market session service."""

from datetime import datetime, timedelta, timezone
import pytest

from app.services.market_session import (
    get_session_state,
    is_market_open,
    SessionState,
)

_IST = timezone(timedelta(hours=5, minutes=30))


def test_market_open_during_trading_hours():
    # Wednesday at 10:00 IST
    dt = datetime(2025, 4, 2, 10, 0, tzinfo=_IST)
    state = get_session_state(dt)
    assert state["state"] == SessionState.MARKET_OPEN.value
    assert state["is_tradeable"] is True


def test_market_closed_evening():
    # Wednesday at 18:00 IST
    dt = datetime(2025, 4, 2, 18, 0, tzinfo=_IST)
    state = get_session_state(dt)
    assert state["state"] == SessionState.CLOSED.value


def test_pre_open_session():
    # Wednesday at 09:05 IST
    dt = datetime(2025, 4, 2, 9, 5, tzinfo=_IST)
    state = get_session_state(dt)
    assert state["state"] == SessionState.PRE_OPEN.value


def test_weekend():
    # Saturday
    dt = datetime(2025, 4, 5, 10, 0, tzinfo=_IST)
    state = get_session_state(dt)
    assert state["state"] == SessionState.WEEKEND.value


def test_is_market_open_util():
    dt = datetime(2025, 4, 2, 12, 0, tzinfo=_IST)
    assert is_market_open(dt) is True

    dt = datetime(2025, 4, 5, 12, 0, tzinfo=_IST)
    assert is_market_open(dt) is False
