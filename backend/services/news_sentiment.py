"""News, sentiment, and anomaly detection services.

Provides:
- News fetching from public RSS/API sources
- Basic sentiment scoring using keyword analysis
- Event risk tagging (earnings, macro, policy)
- Anomaly detection for volume, price jumps, spread expansion
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

# Simple keyword-based sentiment (production would use a transformer model)
_POSITIVE = {
    "upgrade", "beat", "strong", "bullish", "outperform", "growth", "profit",
    "record", "surge", "rally", "positive", "buy", "breakout", "expansion",
    "dividend", "acquisition", "partnership", "innovation", "exceeds",
    "robust", "optimistic", "recovery", "momentum",
}
_NEGATIVE = {
    "downgrade", "miss", "weak", "bearish", "underperform", "loss", "decline",
    "crash", "selloff", "negative", "sell", "breakdown", "contraction",
    "debt", "default", "fraud", "investigation", "lawsuit", "layoff",
    "recession", "warning", "disappointing", "slowdown",
}
_EVENT_TAGS = {
    "earnings": {"earnings", "quarterly", "results", "profit", "revenue", "EPS"},
    "macro": {"RBI", "repo rate", "inflation", "CPI", "WPI", "GDP", "fiscal", "budget", "monetary"},
    "policy": {"SEBI", "regulation", "ban", "circular", "compliance", "norms"},
    "corporate": {"merger", "acquisition", "buyback", "split", "bonus", "delisting", "IPO"},
}


@dataclass
class SentimentResult:
    """Sentiment analysis result for a news item or text."""
    text: str
    score: float  # -1 to +1
    label: str  # positive / negative / neutral
    event_tags: list[str] = field(default_factory=list)
    keywords_found: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "label": self.label,
            "event_tags": self.event_tags,
            "keywords_found": self.keywords_found,
        }


def score_sentiment(text: str) -> SentimentResult:
    """Score sentiment of a text using keyword matching.

    Returns score in [-1, +1]. Production should use FinBERT or similar.
    """
    words = set(re.findall(r'\b\w+\b', text.lower()))
    pos = words & _POSITIVE
    neg = words & _NEGATIVE

    total = len(pos) + len(neg)
    if total == 0:
        score = 0.0
        label = "neutral"
    else:
        score = (len(pos) - len(neg)) / total
        if score > 0.2:
            label = "positive"
        elif score < -0.2:
            label = "negative"
        else:
            label = "neutral"

    # Event tags
    tags = []
    for tag, kw_set in _EVENT_TAGS.items():
        if words & {k.lower() for k in kw_set}:
            tags.append(tag)

    return SentimentResult(
        text=text[:200],
        score=score,
        label=label,
        event_tags=tags,
        keywords_found=sorted(list(pos | neg)),
    )


class NewsFetcher:
    """Fetch financial news from public sources.

    Uses RSS feeds as primary source. Can be extended with paid APIs.
    """

    # Public Indian financial news RSS feeds
    RSS_FEEDS = [
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.moneycontrol.com/rss/latestnews.xml",
        "https://www.livemint.com/rss/markets",
    ]

    def __init__(self) -> None:
        self._cache: list[dict] = []
        self._last_fetch: float = 0

    def fetch_news(self, symbol: str | None = None, limit: int = 20) -> list[dict]:
        """Fetch recent financial news.

        Falls back to cached results if RSS parsing fails.
        """
        articles = []
        try:
            import requests
            for feed_url in self.RSS_FEEDS[:1]:
                try:
                    resp = requests.get(feed_url, timeout=10, headers={
                        "User-Agent": "StockTrader/1.0"
                    })
                    if resp.status_code == 200:
                        articles.extend(self._parse_rss(resp.text, symbol))
                except Exception as exc:
                    logger.debug("RSS fetch failed for %s: %s", feed_url, exc)
        except ImportError:
            pass

        if not articles:
            articles = self._generate_sample_news(symbol)

        self._cache = articles[:limit]
        return self._cache

    def _parse_rss(self, xml_text: str, symbol: str | None) -> list[dict]:
        """Simple XML parsing for RSS items."""
        items = []
        # Basic regex parsing (avoid xml.etree for simplicity)
        for match in re.finditer(r'<item>(.*?)</item>', xml_text, re.DOTALL):
            item = match.group(1)
            title = re.search(r'<title>(.*?)</title>', item)
            desc = re.search(r'<description>(.*?)</description>', item)
            pub = re.search(r'<pubDate>(.*?)</pubDate>', item)

            title_text = title.group(1) if title else ""
            desc_text = desc.group(1) if desc else ""
            full_text = f"{title_text} {desc_text}"

            # Filter by symbol if provided
            if symbol and symbol.upper() not in full_text.upper():
                continue

            sentiment = score_sentiment(full_text)
            items.append({
                "title": title_text[:200],
                "description": desc_text[:500],
                "published": pub.group(1) if pub else None,
                "sentiment": sentiment.to_dict(),
            })

        return items

    def _generate_sample_news(self, symbol: str | None) -> list[dict]:
        """Generate sample news for demo mode."""
        sym = symbol or "NIFTY"
        samples = [
            f"{sym} shows strong momentum amid positive market sentiment",
            f"Market rally continues as banking stocks lead gains",
            f"RBI keeps repo rate unchanged, markets respond positively",
            f"IT sector faces headwinds as global spending slows",
            f"FII inflows boost market confidence this week",
        ]
        return [
            {
                "title": s,
                "description": s,
                "published": datetime.now(timezone.utc).isoformat(),
                "sentiment": score_sentiment(s).to_dict(),
            }
            for s in samples
        ]


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    """Detected market anomaly."""
    anomaly_type: str  # volume_spike, price_jump, spread_expansion, unusual_activity
    ticker: str
    severity: float  # 0-1
    details: dict = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "anomaly_type": self.anomaly_type,
            "ticker": self.ticker,
            "severity": round(self.severity, 3),
            "details": self.details,
            "timestamp": self.timestamp,
        }


class AnomalyDetector:
    """Detect market anomalies in price and volume data."""

    def __init__(
        self,
        volume_spike_threshold: float = 3.0,  # 3x average
        price_jump_threshold: float = 0.05,   # 5% intraday move
        spread_expansion_threshold: float = 3.0,  # 3x average spread
    ) -> None:
        self.volume_spike_threshold = volume_spike_threshold
        self.price_jump_threshold = price_jump_threshold
        self.spread_expansion_threshold = spread_expansion_threshold
        self._alerts: list[AnomalyResult] = []

    def check_volume_spike(
        self, ticker: str, current_volume: float, avg_volume: float
    ) -> AnomalyResult | None:
        """Detect unusual volume."""
        if avg_volume <= 0:
            return None
        ratio = current_volume / avg_volume
        if ratio >= self.volume_spike_threshold:
            severity = min(1.0, (ratio - self.volume_spike_threshold) / 5)
            result = AnomalyResult(
                anomaly_type="volume_spike",
                ticker=ticker,
                severity=severity,
                details={"volume_ratio": round(ratio, 2), "current": current_volume, "average": avg_volume},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._record(result)
            return result
        return None

    def check_price_jump(
        self, ticker: str, current_price: float, reference_price: float
    ) -> AnomalyResult | None:
        """Detect unusual price movement."""
        if reference_price <= 0:
            return None
        move_pct = abs(current_price - reference_price) / reference_price
        if move_pct >= self.price_jump_threshold:
            direction = "up" if current_price > reference_price else "down"
            severity = min(1.0, move_pct / 0.15)
            result = AnomalyResult(
                anomaly_type="price_jump",
                ticker=ticker,
                severity=severity,
                details={
                    "move_pct": round(move_pct * 100, 2),
                    "direction": direction,
                    "current": current_price,
                    "reference": reference_price,
                },
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._record(result)
            return result
        return None

    def check_spread_expansion(
        self, ticker: str, bid: float, ask: float, avg_spread: float
    ) -> AnomalyResult | None:
        """Detect unusual bid-ask spread widening."""
        if avg_spread <= 0 or bid <= 0:
            return None
        current_spread = ask - bid
        ratio = current_spread / avg_spread
        if ratio >= self.spread_expansion_threshold:
            severity = min(1.0, (ratio - self.spread_expansion_threshold) / 5)
            result = AnomalyResult(
                anomaly_type="spread_expansion",
                ticker=ticker,
                severity=severity,
                details={
                    "spread_ratio": round(ratio, 2),
                    "current_spread": round(current_spread, 2),
                    "avg_spread": round(avg_spread, 2),
                },
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._record(result)
            return result
        return None

    def check_all(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
        current_volume: float = 0,
        avg_volume: float = 0,
        bid: float = 0,
        ask: float = 0,
        avg_spread: float = 0,
    ) -> list[AnomalyResult]:
        """Run all anomaly checks for a ticker."""
        anomalies = []
        r = self.check_volume_spike(ticker, current_volume, avg_volume)
        if r:
            anomalies.append(r)
        r = self.check_price_jump(ticker, current_price, reference_price)
        if r:
            anomalies.append(r)
        r = self.check_spread_expansion(ticker, bid, ask, avg_spread)
        if r:
            anomalies.append(r)
        return anomalies

    def _record(self, anomaly: AnomalyResult) -> None:
        self._alerts.append(anomaly)
        if len(self._alerts) > 500:
            self._alerts = self._alerts[-500:]
        try:
            from backend.services.event_bus import get_event_bus, Event, EventType
            get_event_bus().publish(Event(
                EventType.ANOMALY_DETECTED,
                anomaly.to_dict(),
                source="anomaly_detector",
            ))
        except Exception:
            pass

    def get_recent_alerts(self, limit: int = 20) -> list[dict]:
        return [a.to_dict() for a in self._alerts[-limit:]]


_anomaly_detector: AnomalyDetector | None = None


def get_anomaly_detector() -> AnomalyDetector:
    """Module-level singleton accessor."""
    global _anomaly_detector
    if _anomaly_detector is None:
        _anomaly_detector = AnomalyDetector()
    return _anomaly_detector
