# Backtesting endpoint
"""Backtest API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import threading

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestResultsResponse,
    BacktestTrade,
    JobStatus,
)
from backend.prediction_engine.backtest.backtester import Backtester

router = APIRouter(prefix="/backtest", tags=["backtest"])

# In-memory job store (thread-safe; use Celery + DB in production)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


@router.post("/run", response_model=BacktestRunResponse)
async def backtest_run(req: BacktestRunRequest):
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    job = {
        "request": req.model_dump(),
        "status": JobStatus.PENDING,
        "submitted_at": now,
    }

    with _jobs_lock:
        _jobs[job_id] = job

    # Synchronous fallback for local dev (run inline)
    try:
        with _jobs_lock:
            _jobs[job_id]["status"] = JobStatus.RUNNING
        # In a real system this would be dispatched to Celery
        # For now we just mark it as pending and let results be fetched later
        with _jobs_lock:
            _jobs[job_id]["status"] = JobStatus.PENDING
    except Exception:
        with _jobs_lock:
            _jobs[job_id]["status"] = JobStatus.FAILED

    with _jobs_lock:
        status = _jobs[job_id]["status"]

    return BacktestRunResponse(
        job_id=uuid.UUID(job_id),
        status=status,
        submitted_at=now,
    )


@router.get("/{job_id}/results", response_model=BacktestResultsResponse)
async def backtest_results(job_id: str):
    # Try loading from disk first
    result = Backtester.load_result(job_id)
    if result:
        trades = [
            BacktestTrade(**t) for t in result.get("trades", [])
        ]
        return BacktestResultsResponse(
            job_id=uuid.UUID(result["job_id"]),
            status=JobStatus.COMPLETED,
            tickers=result["tickers"],
            start_date=result["start_date"],
            end_date=result["end_date"],
            initial_capital=result["initial_capital"],
            final_value=result["final_value"],
            total_return_pct=result["total_return_pct"],
            sharpe_ratio=result.get("sharpe_ratio"),
            max_drawdown_pct=result.get("max_drawdown_pct"),
            trades=trades,
            completed_at=result.get("completed_at"),
        )

    # Check in-memory jobs
    with _jobs_lock:
        if job_id in _jobs:
            job = _jobs[job_id]
            raise HTTPException(
                status_code=202,
                detail=f"Job {job_id} is {job['status'].value}",
            )

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
