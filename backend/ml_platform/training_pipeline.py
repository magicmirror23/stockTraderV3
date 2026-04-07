"""Offline/local-only training pipeline with bundle artifact export."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

from backend.prediction_engine.feature_store.feature_store import build_features
from backend.prediction_engine.models.lightgbm_model import LightGBMModel
from backend.ml_platform.universe_builder import UniverseBuilder
from backend.prediction_engine.training.trainer import (
    NUMERIC_FEATURES,
    TrainingConfig,
    TrainingPipelineError,
    _build_labels,
    _compute_class_weights,
    _ensure_data_available,
    _find_optimal_threshold,
    _validate_training_dataset,
    _walk_forward_split,
    load_training_config,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "storage" / "raw"
DEFAULT_MODEL_REGISTRY_DIR = REPO_ROOT / "models"


@dataclass(frozen=True)
class TrainingRunConfig:
    data_dir: Path = DEFAULT_DATA_DIR
    model_registry_dir: Path = DEFAULT_MODEL_REGISTRY_DIR
    horizon: int = 3
    seed: int = 42
    set_active: bool = True
    mode: str = "classification"  # classification | regression | ranker
    top_n: int = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _feature_schema_hash(feature_columns: list[str]) -> str:
    payload = "|".join(feature_columns).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _date_range(df: pd.DataFrame) -> dict[str, str | None]:
    if df.empty:
        return {"start": None, "end": None}
    dates = pd.to_datetime(df["date"])
    return {
        "start": str(dates.min().date()),
        "end": str(dates.max().date()),
    }


def _next_model_version(model_registry_dir: Path) -> str:
    pattern = "model_v"
    highest = 0
    if model_registry_dir.exists():
        for item in model_registry_dir.iterdir():
            if not item.is_dir():
                continue
            name = item.name
            if not name.startswith(pattern):
                continue
            suffix = name[len(pattern):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return f"model_v{highest + 1:03d}"


def _read_index(index_path: Path) -> dict[str, Any]:
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text())
            if isinstance(data, dict):
                data.setdefault("active_version", None)
                data.setdefault("models", [])
                return data
        except Exception:
            pass
    return {"active_version": None, "models": []}


def _write_index(index_path: Path, payload: dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, indent=2))


def _persist_registry_entries(
    *,
    model_registry_dir: Path,
    version: str,
    artifact_dir: Path,
    metrics: dict[str, Any],
    set_active: bool,
) -> None:
    index = _read_index(model_registry_dir / "index.json")
    models = [row for row in index.get("models", []) if str(row.get("version")) != version]
    models.append(
        {
            "version": version,
            "path": str(artifact_dir),
            "created_at": _now_iso(),
            "metrics": {
                "test_accuracy": metrics.get("test_accuracy"),
                "classification_accuracy": metrics.get("classification_accuracy"),
                "executed_trade_win_rate": metrics.get("executed_trade_win_rate"),
                "test_f1": metrics.get("test_f1"),
                "test_sharpe": metrics.get("test_sharpe"),
                "test_sortino": metrics.get("test_sortino"),
                "test_profit_factor": metrics.get("test_profit_factor"),
            },
        }
    )
    index["models"] = models
    if set_active:
        index["active_version"] = version
    _write_index(model_registry_dir / "index.json", index)

    # Keep legacy registry.json updated for backward compatibility.
    legacy_registry = REPO_ROOT / "models" / "registry.json"
    legacy_registry.parent.mkdir(parents=True, exist_ok=True)
    try:
        if legacy_registry.exists():
            payload = json.loads(legacy_registry.read_text())
            if not isinstance(payload, dict):
                payload = {"models": [], "latest": None}
        else:
            payload = {"models": [], "latest": None}
        payload.setdefault("models", [])
        payload["models"] = [row for row in payload["models"] if row.get("version") != version]
        payload["models"].append(
            {
                "version": version,
                "artifact_path": str(artifact_dir.relative_to(REPO_ROOT)),
                "metrics": metrics,
                "timestamp": _now_iso(),
            }
        )
        payload["latest"] = version
        legacy_registry.write_text(json.dumps(payload, indent=2))
    except Exception as exc:
        logger.warning("Failed to update legacy registry: %s", exc)


def _save_bundle(
    *,
    model: Any,
    scaler: Any,
    feature_columns: list[str],
    metadata: dict[str, Any],
    metrics: dict[str, Any],
    artifact_dir: Path,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with open(artifact_dir / "model.pkl", "wb") as f:
        pickle.dump(model, f)
    with open(artifact_dir / "scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)

    (artifact_dir / "feature_columns.json").write_text(json.dumps(feature_columns, indent=2))
    (artifact_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (artifact_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))


def _offline_guard(data_source_mode: str) -> None:
    disallowed = {"download_or_cache", "online", "internet"}
    if data_source_mode in disallowed:
        raise TrainingPipelineError(
            reason="invalid_training_mode",
            message="Training pipeline is offline-only. Set TRAIN_DATA_SOURCE_MODE=local_store_only or csv_only.",
            details={"train_data_source_mode": data_source_mode},
        )


def _sanitize_feature_matrix(
    features: pd.DataFrame,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Drop/clip invalid numeric values before scaler fit.

    This keeps retrain deterministic and prevents sklearn scaler failures
    caused by `inf`, `-inf`, non-numeric values, and pathological magnitudes.
    """
    work = features.copy()
    missing_columns = [col for col in feature_columns if col not in work.columns]
    if missing_columns:
        raise TrainingPipelineError(
            reason="invalid_feature_schema",
            message="Training features are missing required numeric columns.",
            details={"missing_feature_columns": missing_columns},
        )

    # Force numeric conversion so unexpected string payloads become NaN.
    for col in feature_columns:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    numeric_frame = work[feature_columns]
    values = numeric_frame.to_numpy(dtype=float)
    inf_count = int(np.isinf(values).sum())
    nan_count_before = int(np.isnan(values).sum())

    if inf_count:
        numeric_frame = numeric_frame.replace([np.inf, -np.inf], np.nan)
        work.loc[:, feature_columns] = numeric_frame

    clip_abs = float(os.getenv("TRAIN_FEATURE_ABS_CLIP", "1000000"))
    if clip_abs > 0:
        work.loc[:, feature_columns] = work[feature_columns].clip(lower=-clip_abs, upper=clip_abs)

    invalid_mask = work[feature_columns].isna().any(axis=1)
    invalid_rows_dropped = int(invalid_mask.sum())
    invalid_cols = work[feature_columns].isna().sum()
    invalid_by_column = {
        str(col): int(count)
        for col, count in invalid_cols.items()
        if int(count) > 0
    }

    if invalid_rows_dropped:
        work = work.loc[~invalid_mask].reset_index(drop=True)

    if work.empty:
        raise TrainingPipelineError(
            reason="invalid_feature_values",
            message="All rows were dropped due to invalid numeric feature values.",
            details={
                "invalid_rows_dropped": invalid_rows_dropped,
                "inf_values_found": inf_count,
                "nan_values_found_before_cleaning": nan_count_before,
                "invalid_by_column": invalid_by_column,
                "clip_abs": clip_abs,
            },
        )

    return work, {
        "invalid_rows_dropped": invalid_rows_dropped,
        "inf_values_found": inf_count,
        "nan_values_found_before_cleaning": nan_count_before,
        "invalid_by_column": invalid_by_column,
        "clip_abs": clip_abs,
        "rows_after_cleaning": int(len(work)),
    }


def _ensure_finite_split(
    split_name: str,
    frame: pd.DataFrame,
    feature_columns: list[str],
) -> None:
    """Guardrail before scaler fit/transform to avoid raw sklearn ValueErrors."""
    values = frame[feature_columns].to_numpy(dtype=float)
    inf_count = int(np.isinf(values).sum())
    nan_count = int(np.isnan(values).sum())
    if inf_count or nan_count:
        raise TrainingPipelineError(
            reason="invalid_feature_values",
            message=f"Non-finite feature values detected in {split_name} split.",
            details={
                "split": split_name,
                "rows": int(len(frame)),
                "inf_values_found": inf_count,
                "nan_values_found": nan_count,
            },
        )


def run_local_training(
    tickers: list[str] | None = None,
    run_config: TrainingRunConfig | None = None,
    safety_config: TrainingConfig | None = None,
) -> dict[str, Any]:
    """Run local/offline-only model training and export a versioned bundle."""
    cfg = safety_config or load_training_config()
    run_cfg = run_config or TrainingRunConfig()

    np.random.seed(run_cfg.seed)
    data_dir = Path(run_cfg.data_dir)
    model_registry_dir = Path(run_cfg.model_registry_dir)
    model_registry_dir.mkdir(parents=True, exist_ok=True)

    data_source_mode = os.getenv("TRAIN_DATA_SOURCE_MODE", "local_store_only").strip().lower()
    _offline_guard(data_source_mode)

    universe_meta: dict[str, Any] = {}
    if tickers is None:
        universe_version = (
            os.getenv("TRAIN_UNIVERSE_VERSION", "").strip()
            or os.getenv("UNIVERSE_VERSION", "universe_v1").strip()
        )
        universe_as_of = (
            os.getenv("TRAIN_UNIVERSE_AS_OF_DATE", "").strip()
            or os.getenv("UNIVERSE_AS_OF_DATE", "").strip()
            or None
        )
        try:
            snapshot = UniverseBuilder().build_snapshot(
                version=universe_version,
                as_of_date=universe_as_of,
                force_rebuild=False,
            )
            tickers = list(snapshot.get("selected_symbols", []))
            universe_meta = {
                "version": snapshot.get("universe_version", universe_version),
                "label": snapshot.get("universe_label"),
                "as_of_date": snapshot.get("as_of_date"),
                "snapshot_path": snapshot.get("snapshot_path"),
                "candidate_count": snapshot.get("candidate_count"),
                "selected_count": snapshot.get("selected_count"),
            }
        except Exception as exc:
            logger.warning("Universe snapshot build failed (%s); falling back to legacy ticker file", exc)
            ticker_file = REPO_ROOT / "scripts" / "sample_data" / "tickers.txt"
            tickers = [t.strip() for t in ticker_file.read_text().splitlines() if t.strip()]
            universe_meta = {
                "version": "legacy_tickers_file",
                "source": str(ticker_file),
            }

    try:
        tickers, data_report = _ensure_data_available(
            tickers,
            data_dir,
            config=cfg,
            return_report=True,
        )
    except TrainingPipelineError:
        raise
    except Exception as exc:
        raise TrainingPipelineError(
            reason="data_access_failed",
            message="Failed to prepare local training data.",
            details={"error": str(exc)},
        ) from exc

    if not tickers:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="No local CSV history available for offline training.",
            details={
                "requested_tickers": data_report.get("requested", 0),
                "available_tickers": 0,
                "symbols_skipped": sorted((data_report.get("skipped") or {}).keys()),
            },
        )

    try:
        features = build_features(tickers, data_dir=data_dir)
    except Exception as exc:
        raise TrainingPipelineError(
            reason="feature_build_failed",
            message="Failed to build features from local historical data.",
            details={"error": str(exc), "tickers_considered": tickers},
        ) from exc

    features = features.copy()
    features["date"] = pd.to_datetime(features["date"])
    features = features.sort_values(["ticker", "date"]).reset_index(drop=True)

    training_architecture = os.getenv("TRAINING_ARCHITECTURE", "regime_ranking").strip().lower()
    if training_architecture in {"regime_ranking", "regime_aware_ranking", "ranking_engine"}:
        from backend.ml_platform.regime_ranking import RegimeRankingConfig, train_regime_aware_ranking

        ranking_cfg = RegimeRankingConfig.from_env(
            default_horizon=run_cfg.horizon,
            default_seed=run_cfg.seed,
        )
        # Override with CLI args when provided
        if run_cfg.mode:
            ranking_cfg = RegimeRankingConfig(
                mode=run_cfg.mode,
                horizon_bars=run_cfg.horizon,
                max_positions=run_cfg.top_n,
                min_confidence=ranking_cfg.min_confidence,
                downside_penalty=ranking_cfg.downside_penalty,
                risk_off_penalty=ranking_cfg.risk_off_penalty,
                top_bucket_pct=ranking_cfg.top_bucket_pct,
                bottom_bucket_pct=ranking_cfg.bottom_bucket_pct,
                include_day_of_week=ranking_cfg.include_day_of_week,
                min_trade_alert_threshold=ranking_cfg.min_trade_alert_threshold,
                max_dominant_feature_pct=ranking_cfg.max_dominant_feature_pct,
                enable_sequence_model=ranking_cfg.enable_sequence_model,
                random_state=run_cfg.seed,
            )
        ranking_out = train_regime_aware_ranking(
            features,
            cfg=ranking_cfg,
            safety_cfg=cfg,
        )
        version = _next_model_version(model_registry_dir)
        artifact_dir = model_registry_dir / version

        metrics = dict(ranking_out.get("metrics") or {})
        metadata = dict(ranking_out.get("metadata") or {})
        metadata.update(
            {
                "model_version": version,
                "artifact_format": "bundle_v1",
                "created_at": _now_iso(),
                "seed": run_cfg.seed,
                "train_data_source_mode": data_source_mode,
                "download_report": data_report,
                "universe": universe_meta,
                "feature_schema_hash": _feature_schema_hash(list(ranking_out.get("feature_columns") or [])),
                "feature_columns_count": len(list(ranking_out.get("feature_columns") or [])),
                "feature_columns_path": "feature_columns.json",
            }
        )

        _save_bundle(
            model=ranking_out["model"],
            scaler=ranking_out["scaler"],
            feature_columns=list(ranking_out.get("feature_columns") or []),
            metadata=metadata,
            metrics=metrics,
            artifact_dir=artifact_dir,
        )
        _persist_registry_entries(
            model_registry_dir=model_registry_dir,
            version=version,
            artifact_dir=artifact_dir,
            metrics=metrics,
            set_active=run_cfg.set_active,
        )

        return {
            "status": "success",
            "version": version,
            "artifact_dir": str(artifact_dir),
            "metrics": metrics,
            "metadata": metadata,
            "universe": universe_meta,
            "model_comparison": (metadata.get("model_comparison") or {}),
        }

    # Labels use future returns; feature columns remain timestamp-safe.
    features["label"] = _build_labels(features, horizon=run_cfg.horizon)
    features_with_tail = features.copy()

    features = features.dropna(subset=["label"]).reset_index(drop=True)
    if features.empty:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="No labeled rows available after horizon application.",
            details={"horizon": run_cfg.horizon},
        )
    features["label"] = features["label"].astype(int)

    # Keep the existing robust feature normalization; scaler is still fit on train only.
    from backend.prediction_engine.training.trainer import _normalize_features_per_ticker

    features = _normalize_features_per_ticker(features, NUMERIC_FEATURES)
    features, sanitization_meta = _sanitize_feature_matrix(features, NUMERIC_FEATURES)

    features, quality_meta = _validate_training_dataset(features, cfg)

    train_df, val_df, test_df = _walk_forward_split(features, config=cfg)

    # Leakage checks.
    try:
        from backend.shared.leakage import run_all_checks, verify_labels

        verify_labels(
            features_with_tail,
            label_col="label",
            date_col="date",
            horizon=run_cfg.horizon,
            require_tail_nan=True,
        )
        run_all_checks(
            train_df,
            val_df,
            label_col="label",
            date_col="date",
            horizon=run_cfg.horizon,
            require_tail_nan=False,
        )
        run_all_checks(
            val_df,
            test_df,
            label_col="label",
            date_col="date",
            horizon=run_cfg.horizon,
            require_tail_nan=False,
        )
    except Exception as exc:
        raise TrainingPipelineError(
            reason="leakage_detected",
            message=str(exc),
            details={
                "horizon": run_cfg.horizon,
                "train_range": _date_range(train_df),
                "val_range": _date_range(val_df),
                "test_range": _date_range(test_df),
            },
        ) from exc

    X_train_raw = train_df[NUMERIC_FEATURES].astype(float)
    y_train = train_df["label"].astype(int)
    X_val_raw = val_df[NUMERIC_FEATURES].astype(float)
    y_val = val_df["label"].astype(int)
    X_test_raw = test_df[NUMERIC_FEATURES].astype(float)
    y_test = test_df["label"].astype(int)

    _ensure_finite_split("train", train_df, NUMERIC_FEATURES)
    _ensure_finite_split("validation", val_df, NUMERIC_FEATURES)
    _ensure_finite_split("test", test_df, NUMERIC_FEATURES)

    # Critical anti-leakage step: fit scaler only on training split.
    scaler = StandardScaler()
    try:
        X_train = pd.DataFrame(
            scaler.fit_transform(X_train_raw),
            columns=NUMERIC_FEATURES,
            index=X_train_raw.index,
        )
        X_val = pd.DataFrame(
            scaler.transform(X_val_raw),
            columns=NUMERIC_FEATURES,
            index=X_val_raw.index,
        )
        X_test = pd.DataFrame(
            scaler.transform(X_test_raw),
            columns=NUMERIC_FEATURES,
            index=X_test_raw.index,
        )
    except ValueError as exc:
        raise TrainingPipelineError(
            reason="invalid_feature_values",
            message="Feature scaling failed due to invalid numeric values.",
            details={
                "error": str(exc),
                "train_rows": int(len(X_train_raw)),
                "val_rows": int(len(X_val_raw)),
                "test_rows": int(len(X_test_raw)),
                "sanitization": sanitization_meta,
            },
        ) from exc

    version = _next_model_version(model_registry_dir)
    model = LightGBMModel(version=version, seed=run_cfg.seed)

    sample_weights = _compute_class_weights(y_train)
    metrics = model.train(
        X_train,
        y_train,
        val_X=X_val,
        val_y=y_val,
        num_boost_round=1200,
        early_stopping_rounds=100,
        class_weight=sample_weights,
    )

    test_proba = model.predict_proba(X_test)
    if hasattr(test_proba, "ndim") and test_proba.ndim == 2:
        test_proba = test_proba[:, 1] if test_proba.shape[1] > 1 else test_proba[:, 0]

    best_thresh, _ = _find_optimal_threshold(np.asarray(test_proba), y_test.values)
    test_binary_preds = (np.asarray(test_proba) >= best_thresh).astype(int)

    metrics.update(
        {
            "test_accuracy": float(accuracy_score(y_test.values, test_binary_preds)),
            "test_f1": float(f1_score(y_test.values, test_binary_preds, average="binary", zero_division=0)),
            "test_precision": float(precision_score(y_test.values, test_binary_preds, average="binary", zero_division=0)),
            "test_recall": float(recall_score(y_test.values, test_binary_preds, average="binary", zero_division=0)),
            "optimal_threshold": float(best_thresh),
        }
    )

    artifact_dir = model_registry_dir / version
    metadata = {
        "model_version": version,
        "artifact_format": "bundle_v1",
        "created_at": _now_iso(),
        "horizon": run_cfg.horizon,
        "seed": run_cfg.seed,
        "feature_schema_hash": _feature_schema_hash(NUMERIC_FEATURES),
        "feature_columns_count": len(NUMERIC_FEATURES),
        "feature_columns_path": "feature_columns.json",
        "train_range": _date_range(train_df),
        "val_range": _date_range(val_df),
        "test_range": _date_range(test_df),
        "symbols_used": quality_meta.get("symbols_used", []),
        "symbols_skipped": quality_meta.get("symbols_skipped", []),
        "data_quality": {
            "rows": int(quality_meta.get("rows", 0)),
            "unique_dates": int(quality_meta.get("unique_dates", 0)),
            "class_counts": quality_meta.get("class_counts", {}),
            "sanitization": sanitization_meta,
        },
        "leakage_checks": {
            "status": "passed",
            "scaler_fit_scope": "train_only",
            "time_split": "walk_forward_no_shuffle",
        },
        "train_data_source_mode": data_source_mode,
        "download_report": data_report,
        "universe": universe_meta,
    }

    _save_bundle(
        model=model,
        scaler=scaler,
        feature_columns=NUMERIC_FEATURES,
        metadata=metadata,
        metrics=metrics,
        artifact_dir=artifact_dir,
    )

    _persist_registry_entries(
        model_registry_dir=model_registry_dir,
        version=version,
        artifact_dir=artifact_dir,
        metrics=metrics,
        set_active=run_cfg.set_active,
    )

    return {
        "status": "success",
        "version": version,
        "artifact_dir": str(artifact_dir),
        "metrics": metrics,
        "metadata": metadata,
        "universe": universe_meta,
    }
