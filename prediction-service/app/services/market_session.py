"""Market session service — tracks IST trading hours and session state.

NSE trading schedule:
  Pre-open:  09:00–09:15 IST
  Market:    09:15–15:30 IST
  Post:      15:30–16:00 IST
  Closed:    otherwise

Saturday/Sunday and NSE holidays are non-trading days.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, time, timezone
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))

# NSE 2025 holidays (can be updated annually)
NSE_HOLIDAYS_2025 = {
    "2025-01-26",  # Republic Day
    "2025-02-26",  # Maha Shivaratri
    "2025-03-14",  # Holi
    "2025-03-31",  # Id-Ul-Fitr
    "2025-04-10",  # Shri Mahavir Jayanti
    "2025-04-14",  # Dr. Ambedkar Jayanti
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day
    "2025-06-07",  # Id-Ul-Adha (Bakri Id)
    "2025-08-15",  # Independence Day
    "2025-08-16",  # Ashura
    "2025-08-27",  # Janmashtami
    "2025-10-02",  # Mahatma Gandhi Jayanti
    "2025-10-20",  # Dussehra
    "2025-10-21",  # Diwali (Laxmi Pujan)
    "2025-10-22",  # Diwali (Balipratipada)
    "2025-11-05",  # Prakash Gurpurb Sri Guru Nanak Dev
    "2025-12-25",  # Christmas
}


class SessionState(str, Enum):
    PRE_OPEN = "pre_open"
    MARKET_OPEN = "market_open"
    POST_MARKET = "post_market"
    CLOSED = "closed"
    HOLIDAY = "holiday"
    WEEKEND = "weekend"


def get_session_state(now: datetime | None = None) -> dict:
    """Return current market session state.

    Returns dict with state, next_event, and time details.
    """
    now = now or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    else:
        now = now.astimezone(_IST)

    date_str = now.strftime("%Y-%m-%d")
    current_time = now.time()

    # Weekend
    if now.weekday() >= 5:
        return {
            "state": SessionState.WEEKEND.value,
            "date": date_str,
            "time_ist": current_time.isoformat(),
            "next_open": _next_trading_day(now).isoformat(),
        }

    # Holiday
    if date_str in NSE_HOLIDAYS_2025:
        return {
            "state": SessionState.HOLIDAY.value,
            "date": date_str,
            "time_ist": current_time.isoformat(),
            "holiday": True,
            "next_open": _next_trading_day(now).isoformat(),
        }

    # Session times
    pre_open = time(9, 0)
    market_open = time(9, 15)
    market_close = time(15, 30)
    post_close = time(16, 0)

    if current_time < pre_open:
        state = SessionState.CLOSED
        next_event = "pre_open at 09:00"
    elif current_time < market_open:
        state = SessionState.PRE_OPEN
        next_event = "market_open at 09:15"
    elif current_time < market_close:
        state = SessionState.MARKET_OPEN
        minutes_left = (datetime.combine(now.date(), market_close) - datetime.combine(now.date(), current_time)).total_seconds() / 60
        next_event = f"market_close at 15:30 ({int(minutes_left)} min)"
    elif current_time < post_close:
        state = SessionState.POST_MARKET
        next_event = "session_end at 16:00"
    else:
        state = SessionState.CLOSED
        next_event = f"next pre_open: {_next_trading_day(now).strftime('%Y-%m-%d')} 09:00"

    return {
        "state": state.value,
        "date": date_str,
        "time_ist": current_time.isoformat(),
        "next_event": next_event,
        "is_tradeable": state == SessionState.MARKET_OPEN,
    }


def _next_trading_day(now: datetime) -> datetime:
    """Find the next trading day (skipping weekends and holidays)."""
    day = now + timedelta(days=1)
    for _ in range(10):
        if day.weekday() < 5 and day.strftime("%Y-%m-%d") not in NSE_HOLIDAYS_2025:
            return day.replace(hour=9, minute=0, second=0, microsecond=0)
        day += timedelta(days=1)
    return day


def is_market_open(now: datetime | None = None) -> bool:
    """Quick check: is the market currently in trading hours?"""
    state = get_session_state(now)
    return state.get("is_tradeable", False)
