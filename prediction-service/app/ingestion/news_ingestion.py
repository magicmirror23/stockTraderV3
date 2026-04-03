"""News ingestion — fetches headlines and computes sentiment scores.

Uses a configurable news API (NewsAPI / GNews) and stores
``SentimentSnapshot`` records for the feature pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)


def _simple_sentiment(text: str) -> float:
    """Rule-based keyword sentiment scorer (–1 to +1).

    Replace with a proper NLP model (FinBERT / VADER) in production.
    """
    text_lower = text.lower()
    positive = [
        "surge", "rally", "gain", "bullish", "upgrade", "beat", "growth",
        "profit", "record high", "boom", "optimism", "recovery", "strong",
    ]
    negative = [
        "crash", "fall", "bearish", "downgrade", "miss", "loss", "decline",
        "cut", "weak", "recession", "fear", "sell-off", "plunge", "risk",
    ]
    pos_count = sum(1 for w in positive if w in text_lower)
    neg_count = sum(1 for w in negative if w in text_lower)
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    return round((pos_count - neg_count) / total, 4)


async def fetch_news_headlines(
    query: str = "India stock market",
    max_articles: int = 20,
) -> list[dict]:
    """Fetch headlines from NewsAPI (or stub if no key)."""
    if not settings.NEWS_API_KEY:
        logger.debug("No NEWS_API_KEY configured, returning empty headlines")
        return []

    try:
        import httpx

        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "sortBy": "publishedAt",
            "pageSize": min(max_articles, 100),
            "apiKey": settings.NEWS_API_KEY,
            "language": "en",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        articles = data.get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""),
                "published_at": a.get("publishedAt", ""),
                "url": a.get("url", ""),
            }
            for a in articles
            if a.get("title")
        ]
    except Exception as exc:
        logger.error("News fetch failed: %s", exc)
        return []


async def compute_news_sentiment(
    instrument: str | None = None,
    sector: str | None = None,
) -> dict:
    """Fetch news and compute aggregate sentiment.

    Returns a dict with news_sentiment, article_count, and individual scores.
    """
    query = instrument or sector or "India stock market NSE"
    articles = await fetch_news_headlines(query)

    if not articles:
        return {"news_sentiment": 0.0, "article_count": 0, "scores": []}

    scores = []
    for a in articles:
        text = f"{a['title']} {a.get('description', '')}"
        score = _simple_sentiment(text)
        scores.append({"title": a["title"], "score": score, "source": a.get("source", "")})

    avg = sum(s["score"] for s in scores) / len(scores) if scores else 0.0

    return {
        "news_sentiment": round(avg, 4),
        "article_count": len(scores),
        "scores": scores,
    }


async def ingest_sentiment_snapshot(
    instrument: str | None = None,
    sector: str | None = None,
) -> None:
    """Compute and persist a sentiment snapshot."""
    from app.db.session import async_session_factory
    from app.db.models import SentimentSnapshot

    result = await compute_news_sentiment(instrument, sector)

    async with async_session_factory() as session:
        record = SentimentSnapshot(
            instrument=instrument,
            sector=sector,
            news_sentiment=result["news_sentiment"],
            composite_score=result["news_sentiment"],
        )
        session.add(record)
        await session.commit()

    logger.info(
        "Sentiment snapshot: instrument=%s sector=%s score=%.4f articles=%d",
        instrument, sector, result["news_sentiment"], result["article_count"],
    )
