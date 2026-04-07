"""Dedicated market-data-service API endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.market_data_service.errors import ProviderFailure
from backend.market_data_service.orchestrator import MarketDataOrchestrator
from backend.market_data_service.validators import frame_to_api_rows

router = APIRouter(tags=["market-data-service"])

_mds = MarketDataOrchestrator()


class ResolveRequest(BaseModel):
    symbol: str = Field(..., min_length=1)


class HistoricalFetchRequest(BaseModel):
    symbols: list[str]
    start_date: str
    end_date: str
    interval: str = "1d"
    min_rows: int = 20
    force: bool = False


class JobBackfillRequest(BaseModel):
    symbols: list[str]
    years: int = 3
    interval: str = "1d"
    min_rows: int = 120


class JobRefreshRequest(BaseModel):
    symbols: list[str]
    lookback_days: int = 45


def _failure_payload(exc: ProviderFailure) -> dict:
    return {
        "status": "failed",
        "reason": exc.code,
        "message": exc.message,
        "provider": exc.provider,
        "details": exc.details,
    }


@router.get("/health/live")
async def health_live():
    return {"status": "ok", "service": "market-data", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/health/ready")
async def health_ready():
    readiness = _mds.store.readiness()
    return {
        "status": "ok" if readiness.get("has_data") else "degraded",
        "service": "market-data",
        "readiness": readiness,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
async def status():
    return _mds.status()


@router.post("/symbols/resolve")
async def resolve_symbol(req: ResolveRequest):
    return _mds.search_symbol(req.symbol)


@router.post("/historical/fetch")
async def historical_fetch(req: HistoricalFetchRequest):
    results = []
    for symbol in req.symbols:
        try:
            results.append(
                _mds.fetch_historical(
                    symbol=symbol,
                    start_date=req.start_date,
                    end_date=req.end_date,
                    interval=req.interval,
                    min_rows=req.min_rows,
                    force=req.force,
                )
            )
        except ProviderFailure as exc:
            results.append({
                "status": "failed",
                "symbol": _mds.resolver.resolve(symbol).canonical_symbol,
                "reason": exc.code,
                "details": exc.details,
            })

    ok = sum(1 for row in results if row.get("status") == "ok")
    return {
        "status": "ok" if ok == len(results) else "partial",
        "requested": len(req.symbols),
        "successful": ok,
        "failed": len(results) - ok,
        "results": results,
    }


@router.get("/historical/query")
async def historical_query(
    symbol: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    interval: str = Query("1d"),
    limit: int | None = Query(default=None),
):
    frame = _mds.query_historical(symbol=symbol, start_date=start_date, end_date=end_date, interval=interval, limit=limit)
    return {
        "status": "ok",
        "symbol": _mds.resolver.resolve(symbol).canonical_symbol,
        "interval": interval,
        "rows": len(frame),
        "data": frame_to_api_rows(frame),
    }


@router.get("/quote/{symbol}")
async def quote(symbol: str, refresh: bool = Query(default=False)):
    try:
        return {"status": "ok", "data": _mds.get_quote(symbol, refresh=refresh)}
    except ProviderFailure as exc:
        return _failure_payload(exc)


@router.get("/provider/status")
async def provider_status():
    return _mds.provider_status()


@router.post("/jobs/backfill")
async def jobs_backfill(req: JobBackfillRequest):
    return _mds.job_backfill_historical_data(
        symbols=req.symbols,
        years=req.years,
        interval=req.interval,
        min_rows=req.min_rows,
    )


@router.post("/jobs/refresh-daily")
async def jobs_refresh_daily(req: JobRefreshRequest):
    return _mds.job_refresh_latest_daily_bars(symbols=req.symbols, lookback_days=req.lookback_days)


@router.post("/jobs/retry-failed")
async def jobs_retry_failed(interval: str = "1d", limit: int = 100):
    return _mds.job_retry_failed_symbols(interval=interval, limit=limit)


@router.post("/jobs/refresh-metadata")
async def jobs_refresh_metadata():
    return _mds.job_refresh_metadata()


@router.get("/historical/export/csv")
async def export_csv(
    symbol: str,
    interval: str = "1d",
    days: int = 730,
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(1, int(days)))
    frame = _mds.query_historical(
        symbol=symbol,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        interval=interval,
    )
    if frame.empty:
        return {
            "status": "failed",
            "reason": "empty_data",
            "message": f"No local bars available for {symbol}",
        }

    csv_data = frame.rename(
        columns={
            "timestamp": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )[["Date", "Open", "High", "Low", "Close", "Volume"]]
    return {
        "status": "ok",
        "symbol": _mds.resolver.resolve(symbol).canonical_symbol,
        "interval": interval,
        "rows": len(csv_data),
        "data": csv_data.to_dict(orient="records"),
    }
