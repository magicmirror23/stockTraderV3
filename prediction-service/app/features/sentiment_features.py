"""Sentiment features — aggregates news/sector/macro sentiment.

Pulls latest SentimentSnapshot records from the DB or computes
on-the-fly from the news ingestion pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


async def get_sentiment_features(
    instrument: str | None = None,
    lookback_hours: int = 72,
) -> dict[str, float]:
    """Fetch recent sentiment snapshots and aggregate into features."""
    from sqlalchemy import select
    from app.db.session import async_session_factory
    from app.db.models import SentimentSnapshot

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    async with async_session_factory() as session:
        stmt = select(SentimentSnapshot).where(
            SentimentSnapshot.timestamp >= cutoff
        ).order_by(SentimentSnapshot.timestamp.desc())

        if instrument:
            stmt = stmt.where(SentimentSnapshot.instrument == instrument)

        result = await session.execute(stmt)
        rows = result.scalars().all()

    if not rows:
        return _empty_sentiment_features()

    news_scores = [r.news_sentiment for r in rows if r.news_sentiment is not None]
    sector_scores = [r.sector_sentiment for r in rows if r.sector_sentiment is not None]
    macro_scores = [r.macro_sentiment for r in rows if r.macro_sentiment is not None]
    composites = [r.composite_score for r in rows if r.composite_score is not None]

    return {
        "sentiment_news_avg": float(np.mean(news_scores)) if news_scores else 0.0,
        "sentiment_news_latest": news_scores[0] if news_scores else 0.0,
        "sentiment_sector_avg": float(np.mean(sector_scores)) if sector_scores else 0.0,
        "sentiment_macro_avg": float(np.mean(macro_scores)) if macro_scores else 0.0,
        "sentiment_composite_avg": float(np.mean(composites)) if composites else 0.0,
        "sentiment_composite_latest": composites[0] if composites else 0.0,
        "sentiment_snapshot_count": float(len(rows)),
        "sentiment_trend": _compute_trend(composites),
    }


def _compute_trend(scores: list[float]) -> float:
    """Simple trend: difference between first-half and second-half average."""
    if len(scores) < 2:
        return 0.0
    mid = len(scores) // 2
    recent = np.mean(scores[:mid])
    older = np.mean(scores[mid:])
    return round(float(recent - older), 4)


def _empty_sentiment_features() -> dict[str, float]:
    keys = [
        "sentiment_news_avg", "sentiment_news_latest",
        "sentiment_sector_avg", "sentiment_macro_avg",
        "sentiment_composite_avg", "sentiment_composite_latest",
        "sentiment_snapshot_count", "sentiment_trend",
    ]
    return {k: 0.0 for k in keys}
