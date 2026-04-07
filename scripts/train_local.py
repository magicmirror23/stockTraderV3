"""Run offline/local model training and export a versioned artifact bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.ml_platform.training_pipeline import TrainingRunConfig, run_local_training


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline StockTrader model training")
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated tickers. If omitted, scripts/sample_data/tickers.txt is used.",
    )
    parser.add_argument(
        "--data-dir",
        default="storage/raw",
        help="Local historical data directory.",
    )
    parser.add_argument(
        "--registry-dir",
        default="models",
        help="Model registry directory for exported bundles.",
    )
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--mode",
        choices=["classification", "regression", "ranker"],
        default="classification",
        help="Ranking pipeline mode: classification (top/bottom bucket), regression, or ranker.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Number of top-ranked symbols to select per rebalance.",
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Do not mark produced model as active in index.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or None

    cfg = TrainingRunConfig(
        data_dir=Path(args.data_dir),
        model_registry_dir=Path(args.registry_dir),
        horizon=args.horizon,
        seed=args.seed,
        set_active=not args.no_activate,
        mode=args.mode,
        top_n=args.top_n,
    )
    result = run_local_training(tickers=tickers, run_config=cfg)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
