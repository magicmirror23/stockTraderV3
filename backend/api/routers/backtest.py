# Backtesting endpoint
"""Backtest API endpoints."""

from __future__ import annotations

import logging
import os
import shutil
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.api.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestResultsResponse,
    BacktestTrade,
    JobStatus,
)
from backend.prediction_engine.backtest.backtester import Backtester, ExecutionConfig
from backend.prediction_engine.feature_store.feature_store import (
    build_features,
    _load_ticker_csv,
)
from backend.services.model_manager import ModelManager
from backend.market_data_service.local_access import LocalMarketDataAccess
from backend.market_data_service.symbols import SymbolResolver
from backend.ml_platform.universe_builder import UniverseBuilder
from backend.ml_platform.universe_definitions import get_symbol_tags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])

STORAGE_RAW = Path(__file__).resolve().parents[3] / "storage" / "raw"

# In-memory job store (thread-safe; use Celery + DB in production)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _coerce_datetime(value: Any) -> Any:
    """Best-effort normalization for legacy timestamp strings.

    Handles malformed values like `2026-04-06T18:50:48.991025+00:00Z`
    written by older builds and returns a `datetime` object when possible.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return None

    # Legacy bug: timezone offset + trailing Z (invalid ISO 8601 for parser).
    if raw.endswith("Z") and ("+" in raw[10:] or "-" in raw[10:]):
        raw = raw[:-1]

    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw[:-1] + "+00:00")
        return datetime.fromisoformat(raw)
    except ValueError:
        return value


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_backtest_tickers(req: BacktestRunRequest) -> tuple[list[str], dict]:
    resolver = SymbolResolver()
    max_tickers = max(1, int(os.getenv("BACKTEST_MAX_TICKERS", "120")))

    if req.tickers:
        symbols = [resolver.normalize(s) for s in req.tickers if str(s).strip()]
        symbols = _ordered_unique(symbols)
        if not symbols:
            raise HTTPException(status_code=400, detail="No valid tickers provided.")
        if len(symbols) > max_tickers:
            symbols = symbols[:max_tickers]
        symbol_tags = {sym: get_symbol_tags(sym) for sym in symbols}
        return symbols, {
            "source": "explicit_request",
            "selected_count": len(symbols),
            "max_tickers": max_tickers,
            "symbol_tags": symbol_tags,
        }

    universe_version = (
        (req.universe_version or "").strip()
        or os.getenv("BACKTEST_UNIVERSE_VERSION", "").strip()
        or os.getenv("UNIVERSE_VERSION", "universe_v1").strip()
    )
    universe_as_of = (
        (req.universe_as_of_date or "").strip()
        or os.getenv("BACKTEST_UNIVERSE_AS_OF_DATE", "").strip()
        or os.getenv("UNIVERSE_AS_OF_DATE", "").strip()
        or None
    )
    snapshot = UniverseBuilder().build_snapshot(
        version=universe_version,
        as_of_date=universe_as_of,
        force_rebuild=False,
    )
    symbols = _ordered_unique(snapshot.get("selected_symbols", []))
    if not symbols:
        raise HTTPException(
            status_code=400,
            detail=f"Universe {universe_version} produced no tradable symbols for backtest.",
        )
    truncated = False
    if len(symbols) > max_tickers:
        symbols = symbols[:max_tickers]
        truncated = True
    raw_tags = snapshot.get("symbol_tags") if isinstance(snapshot.get("symbol_tags"), dict) else {}
    symbol_tags = {}
    for sym in symbols:
        tag = raw_tags.get(sym) if isinstance(raw_tags, dict) else None
        symbol_tags[sym] = tag if isinstance(tag, dict) else get_symbol_tags(sym)

    return symbols, {
        "source": "universe_snapshot",
        "version": snapshot.get("universe_version", universe_version),
        "label": snapshot.get("universe_label"),
        "as_of_date": snapshot.get("as_of_date"),
        "snapshot_path": snapshot.get("snapshot_path"),
        "candidate_count": snapshot.get("candidate_count"),
        "selected_count": len(symbols),
        "max_tickers": max_tickers,
        "truncated": truncated,
        "symbol_tags": symbol_tags,
    }


def _build_execution_predictions(
    features_df: pd.DataFrame,
    preds_raw: list[dict],
) -> pd.DataFrame:
    """Build backtest prediction rows with strict T -> T+1 execution timing.

    Signals are computed from features at `signal_date` and executed on the
    next available bar date for the same ticker to prevent lookahead bias.
    """
    if len(preds_raw) != len(features_df):
        raise ValueError(
            f"Prediction length mismatch: preds={len(preds_raw)} rows, "
            f"features={len(features_df)} rows"
        )

    passthrough_cols = [
        "atr_14",
        "volatility_20",
        "momentum_10",
        "ema_crossover",
        "adx_14",
        "rsi_14",
        "distance_sma50",
        "sector",
        "industry",
    ]
    available_passthrough = [c for c in passthrough_cols if c in features_df.columns]

    # Build one aligned frame first so action/confidence/features stay row-consistent.
    predictions_df = features_df[["date", "ticker", *available_passthrough]].copy()
    predictions_df["action"] = [p.get("action", "hold") for p in preds_raw]
    predictions_df["confidence"] = [float(p.get("confidence", 0.5)) for p in preds_raw]
    predictions_df["model_version"] = [str(p.get("model_version", "unknown")) for p in preds_raw]

    # Strict anti-lookahead: signal computed at T executes at next trading date T+1.
    predictions_df = predictions_df.sort_values(["ticker", "date"]).reset_index(drop=True)
    predictions_df["signal_date"] = predictions_df["date"]
    predictions_df["date"] = predictions_df.groupby("ticker")["date"].shift(-1)
    predictions_df = predictions_df.dropna(subset=["date"]).reset_index(drop=True)
    return predictions_df


def _ensure_backtest_data(
    tickers: list[str],
    start_date: str,
    end_date: str,
    work_dir: Path,
) -> list[Path]:
    """Materialize local stored market bars into work_dir CSV files.

    Backtests must never fetch internet data directly. This hydrates CSVs from
    canonical local storage only.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    materialized: list[Path] = []

    lookback_start = (
        pd.Timestamp(start_date) - pd.DateOffset(days=400)
    ).strftime("%Y-%m-%d")

    access = LocalMarketDataAccess()

    for ticker in tickers:
        dst = work_dir / f"{ticker}.csv"
        try:
            result = access.export_symbol_to_csv(
                symbol=ticker,
                data_dir=work_dir,
                start_date=lookback_start,
                end_date=end_date,
                interval="1d",
                min_rows=220,
            )
            if result.status != "ok" or not result.csv_path:
                logger.warning("Backtest: local data missing for %s (%s)", ticker, result.reason)
                continue
            if Path(result.csv_path) != dst and Path(result.csv_path).exists():
                shutil.copy2(result.csv_path, dst)
            materialized.append(dst if dst.exists() else Path(result.csv_path))
            logger.info("Backtest: materialized %s (%d rows)", ticker, result.rows)
        except Exception as exc:
            logger.error("Backtest: failed to load local data for %s: %s", ticker, exc)

    return materialized


def _predict_features_batch(features_df: pd.DataFrame, mgr: ModelManager) -> list[dict]:
    """Run schema-validated inference row-by-row for strict parity."""
    preds: list[dict] = []
    initial_capital = float(os.getenv("BACKTEST_REFERENCE_CAPITAL", "100000"))
    reference_position_pct = float(
        os.getenv(
            "BACKTEST_REFERENCE_POSITION_PCT",
            os.getenv("PREDICTION_REFERENCE_POSITION_PCT", "0.10"),
        )
    )
    min_edge_bps = float(
        os.getenv(
            "BACKTEST_PREDICTION_MIN_EDGE_BPS",
            os.getenv("PREDICTION_MIN_EDGE_BPS", "6"),
        )
    )
    slippage_bps = float(
        os.getenv(
            "BACKTEST_PREDICTION_SLIPPAGE_BPS",
            os.getenv("PREDICTION_SLIPPAGE_BPS", "2"),
        )
    )

    for row in features_df.to_dict(orient="records"):
        try:
            close_price = float(row.get("close", 0.0) or 0.0)
            if close_price <= 0:
                close_price = 100.0
            reference_qty = max(1, int((initial_capital * reference_position_pct) / close_price))

            pred = mgr.predict_from_features(
                row,
                quantity=reference_qty,
                min_net_edge_bps=min_edge_bps,
                slippage_bps=slippage_bps,
            )
            preds.append(
                {
                    "action": pred.get("action", "hold"),
                    "confidence": float(pred.get("confidence", 0.0)),
                    "model_version": str(pred.get("model_version", "unknown")),
                }
            )
        except Exception as exc:
            logger.debug("Backtest inference fallback hold for %s @ %s: %s", row.get("ticker"), row.get("date"), exc)
            preds.append({"action": "hold", "confidence": 0.0, "model_version": "unknown"})
    return preds


def _run_walk_forward_evaluation(
    *,
    base_job_id: str,
    req_data: dict,
    features_df: pd.DataFrame,
    price_df: pd.DataFrame,
    mgr: ModelManager,
) -> dict[str, Any]:
    """Evaluate rolling test windows across one or more model versions."""
    model_versions = req_data.get("model_versions") or []
    if not model_versions:
        info = mgr.get_model_info()
        model_versions = [info.get("model_version")] if info.get("model_version") else []
    model_versions = [str(v).strip() for v in model_versions if str(v).strip()]
    if not model_versions:
        return {"enabled": True, "status": "skipped", "reason": "no_model_versions"}

    train_days = max(20, int(req_data.get("wf_train_days", 120)))
    test_days = max(5, int(req_data.get("wf_test_days", 30)))
    step_days = max(1, int(req_data.get("wf_step_days", test_days)))

    unique_dates = sorted(pd.to_datetime(features_df["date"]).unique())
    if len(unique_dates) < train_days + test_days:
        return {
            "enabled": True,
            "status": "skipped",
            "reason": "insufficient_dates",
            "unique_dates": len(unique_dates),
            "required": train_days + test_days,
        }

    execution_cfg = ExecutionConfig(
        slippage_pct=float(req_data.get("slippage_pct", 0.001)),
        fill_probability=float(req_data.get("fill_probability", 0.98)),
        use_angel_charges=_to_bool(req_data.get("use_angel_charges", True), True),
        trade_type=str(req_data.get("trade_type", "intraday")),
        commission_per_trade=float(req_data.get("commission_per_trade", 20.0)),
        latency_ms=int(req_data.get("latency_ms", 50)),
        partial_fill_prob=float(req_data.get("partial_fill_prob", 0.0)),
        execution_delay_bars=int(req_data.get("execution_delay_bars", 1)),
    )

    version_payloads: list[dict[str, Any]] = []
    for version in model_versions:
        try:
            mgr.load_version(version)
        except Exception as exc:
            version_payloads.append(
                {
                    "version": version,
                    "status": "failed_load",
                    "error": str(exc),
                    "windows": [],
                }
            )
            continue

        windows: list[dict[str, Any]] = []
        cursor = train_days
        fold = 1
        while cursor + test_days <= len(unique_dates):
            test_start = pd.Timestamp(unique_dates[cursor]).date().isoformat()
            test_end = pd.Timestamp(unique_dates[cursor + test_days - 1]).date().isoformat()

            fold_features = features_df[
                (features_df["date"] >= pd.Timestamp(test_start))
                & (features_df["date"] <= pd.Timestamp(test_end))
            ].reset_index(drop=True)
            fold_prices = price_df[
                (price_df["Date"] >= pd.Timestamp(test_start))
                & (price_df["Date"] <= pd.Timestamp(test_end))
            ].reset_index(drop=True)
            if fold_features.empty or fold_prices.empty:
                cursor += step_days
                fold += 1
                continue

            fold_preds = _predict_features_batch(fold_features, mgr)
            fold_exec = _build_execution_predictions(fold_features, fold_preds)
            if fold_exec.empty:
                cursor += step_days
                fold += 1
                continue

            fold_bt = Backtester(config=execution_cfg)
            fold_job_id = f"{base_job_id}-wf-{version}-fold{fold}"
            fold_result = fold_bt.run(
                fold_exec,
                fold_prices,
                initial_capital=float(req_data.get("initial_capital", 100_000.0)),
                job_id=fold_job_id,
            )
            windows.append(
                {
                    "fold": fold,
                    "train_end": pd.Timestamp(unique_dates[cursor - 1]).date().isoformat(),
                    "test_start": test_start,
                    "test_end": test_end,
                    "total_return_pct": fold_result.total_return_pct,
                    "sharpe_ratio": fold_result.sharpe_ratio,
                    "max_drawdown_pct": fold_result.max_drawdown_pct,
                    "trades": fold_result.total_trades,
                }
            )
            cursor += step_days
            fold += 1

        version_payloads.append(
            {
                "version": version,
                "status": "ok",
                "windows": windows,
                "window_count": len(windows),
                "avg_return_pct": round(
                    statistics.fmean([w["total_return_pct"] for w in windows]), 6
                )
                if windows
                else 0.0,
                "avg_sharpe": round(
                    statistics.fmean(
                        [
                            float(w["sharpe_ratio"])
                            for w in windows
                            if w.get("sharpe_ratio") is not None
                        ]
                    ),
                    6,
                )
                if any(w.get("sharpe_ratio") is not None for w in windows)
                else None,
            }
        )

    return {
        "enabled": True,
        "status": "ok",
        "config": {
            "train_days": train_days,
            "test_days": test_days,
            "step_days": step_days,
        },
        "versions": version_payloads,
    }


def _run_backtest_job(job_id: str, req_data: dict) -> None:
    """Execute the backtest in a background thread."""
    work_dir = STORAGE_RAW.parent / "backtests_tmp" / job_id
    try:
        with _jobs_lock:
            _jobs[job_id]["status"] = JobStatus.RUNNING

        tickers = req_data["tickers"]
        start_date = req_data["start_date"]
        end_date = req_data["end_date"]
        initial_capital = req_data.get("initial_capital", 100_000.0)

        # 1. Ensure data is available — download if needed
        _ensure_backtest_data(tickers, start_date, end_date, work_dir)

        # 2. Build feature matrix from the work directory
        features_df = build_features(
            tickers,
            start=start_date,
            end=end_date,
            data_dir=str(work_dir),
        )
        if features_df.empty:
            raise RuntimeError(
                f"No usable feature rows for {tickers} between {start_date} and {end_date}."
            )

        # Enrich sector/industry tags for by-sector analytics.
        symbol_tags = (
            req_data.get("universe", {}).get("symbol_tags", {})
            if isinstance(req_data.get("universe"), dict)
            else {}
        )
        features_df["sector"] = features_df["ticker"].map(
            lambda s: (
                symbol_tags.get(str(s).upper(), {}).get("sector")
                if isinstance(symbol_tags.get(str(s).upper()), dict)
                else get_symbol_tags(str(s)).get("sector")
            )
            or "Unknown"
        )
        features_df["industry"] = features_df["ticker"].map(
            lambda s: (
                symbol_tags.get(str(s).upper(), {}).get("industry_group")
                if isinstance(symbol_tags.get(str(s).upper()), dict)
                else get_symbol_tags(str(s)).get("industry_group")
            )
            or "Unknown"
        )

        # 3. Generate predictions using inference pipeline (schema-validated parity).
        mgr = ModelManager()
        requested_model_version = str(req_data.get("model_version", "") or "").strip()
        if requested_model_version:
            mgr.load_version(requested_model_version)
        elif mgr.model is None:
            mgr.load_latest()

        preds_raw = _predict_features_batch(features_df, mgr)
        predictions_df = _build_execution_predictions(features_df, preds_raw)
        if predictions_df.empty:
            raise RuntimeError(
                "No executable prediction rows generated (likely insufficient next-bar coverage)."
            )

        # 4. Build price DataFrame from work directory CSVs
        price_frames = []
        for ticker in tickers:
            try:
                raw = _load_ticker_csv(ticker, work_dir)
                raw = raw[["Date", "Close"]].copy()
                raw["ticker"] = ticker
                raw = raw[(raw["Date"] >= pd.Timestamp(start_date)) & (raw["Date"] <= pd.Timestamp(end_date))]
                price_frames.append(raw)
            except FileNotFoundError:
                logger.warning("No price data for %s, skipping", ticker)
        if not price_frames:
            raise RuntimeError("No price data available for any requested ticker")

        price_df = pd.concat(price_frames, ignore_index=True)

        # 5. Run the event-driven backtester
        exec_cfg = ExecutionConfig(
            slippage_pct=float(req_data.get("slippage_pct", 0.001)),
            fill_probability=float(req_data.get("fill_probability", 0.98)),
            use_angel_charges=_to_bool(req_data.get("use_angel_charges", True), True),
            trade_type=str(req_data.get("trade_type", "intraday")),
            commission_per_trade=float(req_data.get("commission_per_trade", 20.0)),
            latency_ms=int(req_data.get("latency_ms", 50)),
            partial_fill_prob=float(req_data.get("partial_fill_prob", 0.0)),
            execution_delay_bars=int(req_data.get("execution_delay_bars", 1)),
        )
        bt = Backtester(config=exec_cfg)
        result = bt.run(
            predictions_df,
            price_df,
            initial_capital=initial_capital,
            job_id=job_id,
        )

        # 6. Optional walk-forward model comparison.
        walk_forward_enabled = _to_bool(req_data.get("walk_forward", False), False)
        if walk_forward_enabled:
            wf_payload = _run_walk_forward_evaluation(
                base_job_id=job_id,
                req_data=req_data,
                features_df=features_df,
                price_df=price_df,
                mgr=mgr,
            )
            result.walk_forward = wf_payload
            Backtester._save_result(result)

        with _jobs_lock:
            _jobs[job_id]["status"] = JobStatus.COMPLETED

        logger.info("Backtest %s completed", job_id)

    except Exception as exc:
        logger.exception("Backtest %s failed", job_id)
        with _jobs_lock:
            _jobs[job_id]["status"] = JobStatus.FAILED
            _jobs[job_id]["error"] = str(exc)
    finally:
        # Clean up temporary data
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info("Backtest %s: cleaned up temp data %s", job_id, work_dir)


@router.post("/run", response_model=BacktestRunResponse)
async def backtest_run(req: BacktestRunRequest):
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    try:
        tickers, universe_meta = _resolve_backtest_tickers(req)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to resolve backtest symbols: {exc}") from exc
    req_payload = req.model_dump()
    req_payload["tickers"] = tickers
    req_payload["universe"] = universe_meta

    job = {
        "request": req_payload,
        "status": JobStatus.PENDING,
        "submitted_at": now,
    }

    with _jobs_lock:
        _jobs[job_id] = job

    # Run in a background thread so the endpoint returns immediately
    thread = threading.Thread(
        target=_run_backtest_job,
        args=(job_id, req_payload),
        daemon=True,
    )
    thread.start()

    return BacktestRunResponse(
        job_id=uuid.UUID(job_id),
        status=JobStatus.PENDING,
        submitted_at=now,
    )


@router.get("/{job_id}/results", response_model=BacktestResultsResponse)
async def backtest_results(job_id: str):
    # Try loading from disk first (completed jobs persist to JSON)
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
            sortino_ratio=result.get("sortino_ratio"),
            max_drawdown_pct=result.get("max_drawdown_pct"),
            cagr_pct=result.get("cagr_pct"),
            total_charges=result.get("total_charges", 0),
            win_rate=result.get("win_rate"),
            avg_win=result.get("avg_win"),
            avg_loss=result.get("avg_loss"),
            expectancy=result.get("expectancy"),
            total_trades=result.get("total_trades", 0),
            no_trade_count=result.get("no_trade_count", 0),
            rejection_count=result.get("rejection_count", 0),
            turnover=result.get("turnover", 0.0),
            avg_holding_bars=result.get("avg_holding_bars"),
            median_holding_bars=result.get("median_holding_bars"),
            win_loss_distribution=result.get("win_loss_distribution", {}),
            metrics_by_symbol=result.get("metrics_by_symbol", {}),
            metrics_by_sector=result.get("metrics_by_sector", {}),
            metrics_by_regime=result.get("metrics_by_regime", {}),
            equity_curve=result.get("equity_curve", []),
            drawdown_curve=result.get("drawdown_curve", []),
            walk_forward=result.get("walk_forward", {}),
            trades=trades,
            completed_at=_coerce_datetime(result.get("completed_at")),
        )

    # Check in-memory jobs for pending/running/failed status
    with _jobs_lock:
        if job_id in _jobs:
            job = _jobs[job_id]
            status = job["status"]
            # Return status as 200 JSON so the frontend polling can read it
            return JSONResponse(
                status_code=200,
                content={
                    "job_id": job_id,
                    "status": status.value,
                    "tickers": job["request"]["tickers"],
                    "start_date": job["request"]["start_date"],
                    "end_date": job["request"]["end_date"],
                    "initial_capital": job["request"].get("initial_capital", 100000),
                    "final_value": 0,
                    "total_return_pct": 0,
                    "turnover": 0,
                    "trades": [],
                    "equity_curve": [],
                    "drawdown_curve": [],
                    "completed_at": None,
                    "error": job.get("error"),
                },
            )

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
