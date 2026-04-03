"""Centralised configuration via pydantic-settings.

Every tuneable parameter lives here.  Values come from environment variables
(or a `.env` file loaded by the Settings model automatically).

Usage::

    from app.core.config import settings
    print(settings.DATABASE_URL)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SERVICE_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings – populated from env / .env."""

    model_config = SettingsConfigDict(
        env_file=str(_SERVICE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Service identity ─────────────────────────────────────────────
    SERVICE_NAME: str = "prediction-service"
    SERVICE_VERSION: str = "1.0.0"
    SERVICE_PORT: int = 8010
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── Database ─────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./prediction_service.db"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False

    # ── Redis ────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/1"
    CACHE_TTL_SECONDS: int = 300

    # ── Angel One broker credentials ─────────────────────────────────
    ANGEL_API_KEY: str = ""
    ANGEL_CLIENT_ID: str = ""
    ANGEL_CLIENT_PIN: str = ""
    ANGEL_TOTP_SECRET: str = ""
    ANGEL_API_BASE_URL: str = "https://apiconnect.angelone.in"
    ANGEL_TOKEN_CACHE_PATH: str = "storage/runtime/angel_tokens.json"

    # ── Data provider ────────────────────────────────────────────────
    DATA_PROVIDER: str = "angel_one"  # angel_one | yahoo | mock
    MARKET_DATA_DIR: str = str(_SERVICE_ROOT.parent / "storage" / "raw")

    # ── News / Sentiment ─────────────────────────────────────────────
    NEWS_API_KEY: str = ""
    NEWS_API_URL: str = "https://newsapi.org/v2"
    SENTIMENT_MODEL: str = "keyword"  # keyword | transformer

    # ── Model artefacts ──────────────────────────────────────────────
    MODEL_ARTIFACTS_DIR: str = str(_SERVICE_ROOT / "artifacts")
    MODEL_REGISTRY_PATH: str = str(_SERVICE_ROOT / "artifacts" / "registry.json")
    DEFAULT_MODEL_VERSION: str = "latest"

    # ── Training defaults ────────────────────────────────────────────
    TRAIN_LOOKBACK_YEARS: int = 3
    TRAIN_WALK_FORWARD_FOLDS: int = 5
    TRAIN_PURGE_DAYS: int = 10
    TRAIN_EMBARGO_DAYS: int = 5
    LABEL_HORIZON_DAYS: int = 1
    LABEL_THRESHOLD: float = 0.005  # 0.5% move threshold
    MAX_TRAINING_TICKERS: int = 60

    # ── Inference ────────────────────────────────────────────────────
    PREDICTION_CONFIDENCE_THRESHOLD: float = 0.55
    STALE_TICK_SECONDS: int = 300
    WARMUP_TICKS: int = 50
    MAX_BATCH_SIZE: int = 100

    # ── Monitoring ───────────────────────────────────────────────────
    PROMETHEUS_ENABLED: bool = True
    DRIFT_CHECK_INTERVAL_HOURS: float = 6.0

    # ── Market session (IST) ─────────────────────────────────────────
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    MARKET_OPEN_TIME: str = "09:15"
    MARKET_CLOSE_TIME: str = "15:30"
    PRE_OPEN_START: str = "09:00"
    POST_CLOSE_END: str = "15:45"

    # ── Backtest ─────────────────────────────────────────────────────
    BROKERAGE_BPS: float = 3.0  # brokerage in basis points
    SLIPPAGE_BPS: float = 5.0
    LATENCY_MS: float = 50.0

    # ── Tickers ──────────────────────────────────────────────────────
    DEFAULT_TICKERS: list[str] = [
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
        "SBIN", "AXISBANK", "KOTAKBANK", "BAJFINANCE", "BAJAJFINSV",
        "HINDUNILVR", "ITC", "LT", "MARUTI", "TITAN",
        "SUNPHARMA", "DRREDDY", "CIPLA", "WIPRO", "HCLTECH",
        "TECHM", "TATASTEEL", "HINDALCO", "JSWSTEEL", "COALINDIA",
        "ONGC", "BPCL", "NTPC", "POWERGRID", "ADANIENT",
        "ASIANPAINT", "ULTRACEMCO", "GRASIM", "NESTLEIND",
        "TATAMOTORS", "EICHERMOT", "HEROMOTOCO",
        "DIVISLAB", "APOLLOHOSP", "TRENT",
    ]

    MACRO_SYMBOLS: list[str] = [
        "^NSEI", "^NSEBANK", "^BSESN",
        "^VIX",
        "CL=F", "GC=F",
        "USDINR=X",
        "^GSPC", "^IXIC", "^DJI",
        "^FTSE", "^N225",
    ]

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
