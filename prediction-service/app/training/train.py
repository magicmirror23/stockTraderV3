"""Training orchestrator — end-to-end model training flow.

Steps:
1. Load data (CSV/provider)
2. Build features
3. Split temporally (with purge + embargo)
4. Train model(s)
5. Walk-forward stability check
6. Fit + save calibrator on validation set
7. Validate on held-out test
8. Gate on minimum quality — reject unstable models
9. Save artifacts & metadata
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.metrics import TRAINING_COUNT, TRAINING_DURATION

logger = logging.getLogger(__name__)

_MIN_TEST_AUC = 0.53  # reject models below this on holdout test
_MIN_WF_STABILITY = True   # require walk-forward stability flag


async def run_training(
    model_type: str = "lightgbm",
    tickers: list[str] | None = None,
    retrain: bool = False,
) -> dict[str, Any]:
    """Execute a full training run.

    Args:
        model_type: One of lightgbm, xgboost, random_forest, ensemble.
        tickers: Override default tickers.
        retrain: If True, force retraining even if a recent model exists.

    Returns:
        Dict with model_version, metrics, artifact_path, walk_forward, etc.
    """
    from app.ingestion.historical_loader import load_multi_ticker
    from app.features.feature_pipeline import build_features_for_training
    from app.training.dataset_builder import temporal_split, check_for_leakage
    from app.training.validate import compute_metrics
    from app.training.walk_forward import walk_forward_validation
    from app.inference.confidence import fit_calibrator, save_calibrator
    from app.db.session import async_session_factory
    from app.db.models import TrainingRun, ModelMetadata

    start_time = time.time()
    version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d.%H%M%S')}"
    tickers = tickers or settings.DEFAULT_TICKERS

    # Record training run
    run_record = TrainingRun(
        status="running",
        model_version=version,
        config={"model_type": model_type, "tickers": tickers[:5], "ticker_count": len(tickers)},
    )
    async with async_session_factory() as session:
        session.add(run_record)
        await session.commit()
        run_id = run_record.id

    try:
        # 1. Load data
        logger.info("Loading data for %d tickers...", len(tickers))
        data = load_multi_ticker(tickers, prefer_csv=True)
        if not data:
            raise RuntimeError("No data loaded for any ticker")

        # 2. Build features
        logger.info("Building features...")
        features_df = build_features_for_training(data)
        if features_df.empty:
            raise RuntimeError("Feature construction produced empty DataFrame")

        # 3. Temporal split (with purge + embargo)
        logger.info("Splitting dataset...")
        split = temporal_split(features_df)
        leakage_warnings = check_for_leakage(split)

        # 4. Create model
        model = _create_model(model_type)

        # 5. Train
        logger.info("Training %s model...", model_type)
        eval_set = (split.X_val, split.y_val) if len(split.X_val) > 0 else None
        train_metrics = model.fit(
            split.X_train, split.y_train,
            eval_set=eval_set,
            early_stopping_rounds=50,
        )

        # 6. Walk-forward stability check
        logger.info("Running walk-forward validation...")
        wf_result = walk_forward_validation(
            model_factory=lambda: _create_model(model_type),
            features_df=features_df,
        )
        wf_stable = wf_result.stability_metrics.get("is_stable", False) if wf_result.stability_metrics else False
        wf_summary = {
            "n_folds": len(wf_result.fold_results),
            "rejected_folds": wf_result.rejected_folds,
            "stability": wf_result.stability_metrics,
        }
        logger.info(
            "Walk-forward: %d folds, stable=%s, mean_auc=%.4f",
            len(wf_result.fold_results),
            wf_stable,
            wf_result.stability_metrics.get("auc_mean", 0) if wf_result.stability_metrics else 0,
        )

        # 7. Validate on held-out test
        logger.info("Validating on test set...")
        test_proba = model.predict_proba(split.X_test)
        test_preds = (test_proba > 0.5).astype(int)
        val_proba = model.predict_proba(split.X_val)
        val_preds = (val_proba > 0.5).astype(int)

        test_metrics = compute_metrics(split.y_test, test_preds, test_proba)
        val_metrics = compute_metrics(split.y_val, val_preds, val_proba)

        # 8. Fit + save calibrator on validation predictions
        calibrator_saved = False
        if len(split.y_val) > 20:
            try:
                calibrator = fit_calibrator(split.y_val, val_proba, method="isotonic")
                save_calibrator(calibrator, version)
                calibrator_saved = True
                logger.info("Calibrator (isotonic) saved for %s", version)
            except Exception as exc:
                logger.warning("Calibrator fitting failed: %s", exc)

        # 9. Quality gate — reject models below minimum AUC or unstable walk-forward
        test_auc = test_metrics.get("auc", 0.0)
        model_status = "trained"
        rejection_reasons: list[str] = []

        if test_auc < _MIN_TEST_AUC:
            rejection_reasons.append(f"test_auc={test_auc:.4f} < {_MIN_TEST_AUC}")
        if _MIN_WF_STABILITY and not wf_stable:
            rejection_reasons.append("walk-forward unstable")

        if rejection_reasons:
            model_status = "rejected"
            logger.warning(
                "Model %s REJECTED: %s", version, "; ".join(rejection_reasons),
            )

        # 10. Save artifacts
        artifact_dir = Path(settings.MODEL_ARTIFACTS_DIR) / version
        artifact_dir.mkdir(parents=True, exist_ok=True)
        model_path = str(artifact_dir / "model.joblib")
        model.save(model_path)

        meta_path = artifact_dir / "meta.json"
        meta_path.write_text(json.dumps({
            "version": version,
            "model_type": model_type,
            "status": model_status,
            "feature_names": split.feature_names,
            "train_rows": len(split.X_train),
            "test_metrics": test_metrics,
            "val_metrics": val_metrics,
            "walk_forward": wf_summary,
            "calibrator_saved": calibrator_saved,
            "rejection_reasons": rejection_reasons,
        }, indent=2, default=str))

        # Ensemble component metrics
        component_metrics = {}
        if hasattr(model, "component_metrics"):
            component_metrics = model.component_metrics

        feature_importance = model.get_feature_importance()

        duration = time.time() - start_time
        TRAINING_DURATION.observe(duration)
        TRAINING_COUNT.labels(model_type=model_type, status="success").inc()

        # 11. Save metadata to DB
        async with async_session_factory() as session:
            model_meta = ModelMetadata(
                version=version,
                model_type=model_type,
                status=model_status,
                params={"model_type": model_type},
                train_metrics=train_metrics,
                val_metrics=val_metrics,
                test_metrics=test_metrics,
                feature_importance=dict(
                    sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:20]
                ),
                artifact_path=model_path,
                tickers_count=len(data),
                training_rows=len(split.X_train),
                walk_forward_folds=len(wf_result.fold_results),
            )
            session.add(model_meta)
            await session.commit()

        # Update training run
        async with async_session_factory() as session:
            from sqlalchemy import update
            stmt = update(TrainingRun).where(TrainingRun.id == run_id).values(
                status="success" if model_status == "trained" else "rejected",
                finished_at=datetime.now(timezone.utc),
                duration_seconds=duration,
                model_version=version,
                metrics=test_metrics,
            )
            await session.execute(stmt)
            await session.commit()

        result = {
            "version": version,
            "model_type": model_type,
            "status": model_status,
            "train_metrics": train_metrics,
            "val_metrics": val_metrics,
            "test_metrics": test_metrics,
            "walk_forward": wf_summary,
            "artifact_path": model_path,
            "training_rows": len(split.X_train),
            "tickers": len(data),
            "duration_seconds": round(duration, 2),
            "leakage_warnings": leakage_warnings,
            "calibrator_saved": calibrator_saved,
            "rejection_reasons": rejection_reasons,
            "component_metrics": component_metrics,
        }

        logger.info(
            "Training complete: %s status=%s auc=%.4f in %.1fs",
            version, model_status, test_auc, duration,
        )
        return result

    except Exception as exc:
        duration = time.time() - start_time
        TRAINING_COUNT.labels(model_type=model_type, status="failed").inc()

        async with async_session_factory() as session:
            from sqlalchemy import update
            stmt = update(TrainingRun).where(TrainingRun.id == run_id).values(
                status="failed",
                finished_at=datetime.now(timezone.utc),
                duration_seconds=duration,
                error_message=str(exc),
            )
            await session.execute(stmt)
            await session.commit()

        logger.error("Training failed: %s", exc)
        raise


def _create_model(model_type: str):
    """Factory for creating model instances."""
    if model_type == "lightgbm":
        from app.models.tree_models import LightGBMModel
        return LightGBMModel()
    elif model_type == "xgboost":
        from app.models.tree_models import XGBoostModel
        return XGBoostModel()
    elif model_type == "random_forest":
        from app.models.baselines import RandomForestModel
        return RandomForestModel()
    elif model_type == "logistic_regression":
        from app.models.baselines import LogisticRegressionModel
        return LogisticRegressionModel()
    elif model_type == "ensemble":
        from app.models.ensemble import build_default_ensemble
        return build_default_ensemble()
    else:
        raise ValueError(f"Unknown model type: {model_type}")
