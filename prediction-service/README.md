# Prediction Service

AI-powered stock direction prediction microservice for NSE (National Stock Exchange of India).

## Architecture

```
prediction-service/
├── app/
│   ├── api/                    # FastAPI routes
│   │   ├── routes_health.py    # Health checks, metrics, status
│   │   ├── routes_predict.py   # Prediction endpoints
│   │   ├── routes_models.py    # Model training & management
│   │   └── routes_market_session.py  # Market session, events, drift
│   ├── core/                   # Configuration & infrastructure
│   │   ├── __init__.py         # Settings (pydantic-settings)
│   │   ├── config.py           # Re-export
│   │   ├── logging.py          # Structured JSON logging
│   │   └── metrics.py          # Prometheus metrics
│   ├── db/                     # Database layer
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   └── session.py          # Async session factory
│   ├── features/               # Feature engineering
│   │   ├── market_features.py  # OHLCV technical indicators
│   │   ├── options_features.py # IV, PCR, Greeks, OI
│   │   ├── macro_features.py   # VIX, crude, gold, USD/INR
│   │   ├── event_features.py   # Geopolitical event signals
│   │   ├── sentiment_features.py # News sentiment
│   │   └── feature_pipeline.py # Unified pipeline
│   ├── ingestion/              # Data ingestion
│   │   ├── historical_loader.py # CSV + API bulk loader
│   │   ├── live_market_stream.py # Real-time tick polling
│   │   ├── event_ingestion.py  # Event scoring pipeline
│   │   └── news_ingestion.py   # News API + sentiment
│   ├── inference/              # Prediction pipeline
│   │   ├── predictor.py        # Main inference entry
│   │   ├── regime_router.py    # Regime-aware routing
│   │   ├── confidence.py       # Calibration & thresholds
│   │   └── explainability.py   # SHAP / feature importance
│   ├── models/                 # ML model definitions
│   │   ├── baselines.py        # LogisticRegression, RandomForest
│   │   ├── tree_models.py      # LightGBM, XGBoost
│   │   ├── sequence_models.py  # LSTM, GRU (PyTorch)
│   │   ├── regime_model.py     # KMeans regime classifier
│   │   └── ensemble.py         # Weighted ensemble
│   ├── monitoring/             # Production monitoring
│   │   └── drift.py            # PSI, calibration drift
│   ├── providers/              # Market data providers
│   │   ├── base.py             # Abstract base + dataclasses
│   │   ├── angel_one.py        # Angel One SmartAPI
│   │   └── factory.py          # Provider factory
│   ├── services/               # Business services
│   │   ├── market_session.py   # NSE trading hours
│   │   ├── model_registry.py   # Version management
│   │   └── cache.py            # Redis / memory cache
│   ├── training/               # Training pipeline
│   │   ├── dataset_builder.py  # Time-series safe splits
│   │   ├── train.py            # Training orchestrator
│   │   ├── validate.py         # Metrics & calibration
│   │   └── walk_forward.py     # Walk-forward CV
│   └── main.py                 # FastAPI app entry point
├── tests/                      # Test suite
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

## Quick Start

```bash
# 1. Install dependencies
cd prediction-service
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your settings

# 3. Run
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

## API Endpoints

| Method | Endpoint                    | Description                    |
|--------|-----------------------------|--------------------------------|
| GET    | /api/v1/health              | Health check                   |
| GET    | /api/v1/health/ready        | Readiness probe                |
| GET    | /api/v1/status              | Detailed service status        |
| GET    | /api/v1/metrics             | Prometheus metrics             |
| POST   | /api/v1/predict             | Single prediction              |
| POST   | /api/v1/predict/batch       | Batch predictions              |
| GET    | /api/v1/predict/{symbol}    | GET-based prediction           |
| POST   | /api/v1/models/train        | Trigger model training         |
| GET    | /api/v1/models/train/status | Check training status          |
| GET    | /api/v1/models/active       | Active model info              |
| GET    | /api/v1/models/list         | List all models                |
| POST   | /api/v1/models/promote/{v}  | Promote model version          |
| GET    | /api/v1/market-session      | NSE market session state       |
| GET    | /api/v1/events/active       | Active events                  |
| POST   | /api/v1/events/ingest       | Ingest new event               |
| GET    | /api/v1/drift               | Drift detection report         |

## Docker

```bash
docker build -t prediction-service .
docker run -p 8010:8010 --env-file .env prediction-service
```
