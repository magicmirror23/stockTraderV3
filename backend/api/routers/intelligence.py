"""News, sentiment, and anomaly detection API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["news-sentiment-anomaly"])


# --------------- Sentiment ---------------

@router.post("/sentiment/score")
async def score_text(payload: dict):
    """Score sentiment of arbitrary text.

    Body: {text: str}
    """
    from backend.services.news_sentiment import score_sentiment
    result = score_sentiment(payload.get("text", ""))
    return {
        "score": result.score,
        "label": result.label,
        "event_tags": result.event_tags,
        "keywords_found": result.keywords_found,
    }


# --------------- News ---------------

@router.get("/news/{symbol}")
async def fetch_news(symbol: str, limit: int = 10):
    """Fetch recent news for a symbol with sentiment scores."""
    from backend.services.news_sentiment import NewsFetcher, score_sentiment as _score
    fetcher = NewsFetcher()
    articles = fetcher.fetch_news(symbol, limit=limit)
    for art in articles:
        sr = _score(art.get("title", "") + " " + art.get("summary", ""))
        art["sentiment"] = {"score": sr.score, "label": sr.label, "event_tags": sr.event_tags}
    return articles


# --------------- Anomaly Detection ---------------

@router.post("/anomaly/check")
async def check_anomalies(payload: dict):
    """Run anomaly detection suite for a ticker.

    Body: {ticker, current_price, reference_price, current_volume?,
           avg_volume?, bid?, ask?, avg_spread?}
    """
    from backend.services.news_sentiment import get_anomaly_detector
    detector = get_anomaly_detector()
    alerts = detector.check_all(
        ticker=payload["ticker"],
        current_price=float(payload["current_price"]),
        reference_price=float(payload["reference_price"]),
        current_volume=float(payload.get("current_volume", 0)),
        avg_volume=float(payload.get("avg_volume", 1)),
        bid=float(payload.get("bid", 0)),
        ask=float(payload.get("ask", 0)),
        avg_spread=float(payload.get("avg_spread", 0.01)),
    )
    return [
        {
            "type": a.anomaly_type,
            "ticker": a.ticker,
            "severity": a.severity,
            "value": a.value,
            "threshold": a.threshold,
            "message": a.message,
        }
        for a in alerts
    ]


@router.get("/anomaly/alerts")
async def recent_alerts(limit: int = 20):
    """Recent anomaly alerts."""
    from backend.services.news_sentiment import get_anomaly_detector
    return get_anomaly_detector().get_recent_alerts(limit)
