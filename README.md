# StockTrader

Full-stack autonomous AI stock & options trading platform built with **FastAPI**, **Angular 19 + TypeScript**, **LightGBM + XGBoost + LSTM ensemble**, **PostgreSQL/SQLite**, and **Redis**.

## Repository Structure

```
├── backend/                          # Monolith API server (port 8000)
│   ├── api/                          # FastAPI app, schemas, middleware
│   │   └── routers/                  # 18 route modules
│   │       ├── health.py             # Health & readiness probes
│   │       ├── predict.py            # Equity & batch predictions
│   │       ├── options.py            # Options signals, Greeks, strategies
│   │       ├── model.py              # Model status, reload, retrain
│   │       ├── backtest.py           # Backtest engine
│   │       ├── trade.py              # Trade intents & execution
│   │       ├── paper.py              # Paper trading accounts
│   │       ├── stream.py             # WebSocket + SSE price feeds
│   │       ├── portfolio.py          # Portfolio dashboard & analytics
│   │       ├── risk.py               # Risk management & limits
│   │       ├── strategy.py           # Strategy builder & signals
│   │       ├── market.py             # Market session & regime
│   │       ├── intelligence.py       # AI insights & intelligence
│   │       ├── execution.py          # Execution quality analytics
│   │       ├── bot.py                # Auto-trading bot lifecycle
│   │       ├── orchestrator.py       # Market orchestrator
│   │       └── admin.py              # Admin & system management
│   ├── prediction_engine/
│   │   ├── data_pipeline/            # Yahoo/NSE/IV/news connectors, validation
│   │   ├── feature_store/            # Feature transforms, selection, versioned store
│   │   ├── models/                   # BaseModel, LightGBM, XGBoost, LSTM, Ensemble
│   │   ├── training/                 # Walk-forward splits + ensemble trainer
│   │   ├── backtest/                 # Backtester engine
│   │   └── monitoring/               # Drift detection (KS/PSI), canary deployment
│   ├── trading_engine/               # Order manager, Angel One adapter, simulator
│   ├── paper_trading/                # Paper accounts, executor, replayer
│   ├── services/                     # 22 business services
│   │   ├── model_manager.py          # Model lifecycle management
│   │   ├── model_registry.py         # Version registry (JSON-backed)
│   │   ├── monitoring.py             # Drift & health monitoring
│   │   ├── mlflow_registry.py        # MLflow integration
│   │   ├── regime_detector.py        # Market regime classification
│   │   ├── risk_manager.py           # Position limits & risk rules
│   │   ├── portfolio_intelligence.py # Portfolio analytics & AI insights
│   │   ├── strategy_intelligence.py  # Strategy recommendation engine
│   │   ├── options_strategy.py       # Options strategy builder
│   │   ├── news_sentiment.py         # News API + sentiment scoring
│   │   ├── price_feed.py             # Real-time price feeds
│   │   ├── angel_feed.py             # Angel One data feed
│   │   ├── data_downloader.py        # yfinance bulk downloader (52 NSE tickers)
│   │   ├── market_hours.py           # NSE session & holiday calendar
│   │   ├── market_orchestrator.py    # Scheduled market tasks
│   │   ├── bot_lifecycle.py          # Auto-trading bot management
│   │   ├── execution_quality.py      # Fill quality & slippage analysis
│   │   ├── advanced_risk.py          # VaR, stress testing, Greeks risk
│   │   ├── brokerage_calculator.py   # Brokerage & tax computation
│   │   ├── event_bus.py              # In-process event bus
│   │   └── celery_tasks.py           # Async task scheduling
│   ├── db/                           # SQLAlchemy models & async session
│   ├── tests/                        # pytest test suite
│   └── scripts/                      # Client example scripts
├── frontend/                         # Angular 19 SPA (port 4200)
│   └── src/app/
│       ├── pages/                    # 16 page components
│       │   ├── trading/              # Main trading dashboard
│       │   ├── portfolio-dashboard/  # Portfolio overview & analytics
│       │   ├── risk-dashboard/       # Risk metrics & monitoring
│       │   ├── signal-explorer/      # Signal discovery
│       │   ├── signal-detail/        # Signal deep-dive
│       │   ├── paper-dashboard/      # Paper trading overview
│       │   ├── paper-account-detail/ # Paper account details
│       │   ├── live-chart/           # Real-time price charts
│       │   ├── live-market/          # Live market overview
│       │   ├── options-builder/      # Options strategy builder
│       │   ├── backtest/             # Backtest launcher & results
│       │   ├── bot-panel/            # Auto-trading bot management
│       │   ├── regime-panel/         # Market regime visualisation
│       │   ├── news-feed/            # News & sentiment feed
│       │   ├── execution-quality/    # Execution analytics
│       │   └── admin/                # Admin panel
│       ├── components/               # Reusable UI components
│       │   ├── equity-chart/         # Equity curve chart
│       │   ├── live-price-chart/     # Real-time price chart
│       │   ├── order-intent-form/    # Order entry form
│       │   ├── simulation-summary-card/ # Simulation results card
│       │   ├── sparkline/            # Inline sparkline chart
│       │   └── ticker-tape/          # Scrolling ticker tape
│       └── services/                 # 17 API services
│           ├── prediction-api/       # Prediction endpoints
│           ├── paper-api/            # Paper trading endpoints
│           ├── portfolio-api/        # Portfolio endpoints
│           ├── risk-api/             # Risk endpoints
│           ├── strategy-api/         # Strategy endpoints
│           ├── options-api/          # Options endpoints
│           ├── trade-api/            # Trade endpoints
│           ├── market-api/           # Market data endpoints
│           ├── backtest-api/         # Backtest endpoints
│           ├── intelligence-api/     # Intelligence endpoints
│           ├── execution-api/        # Execution endpoints
│           ├── admin-api/            # Admin endpoints
│           ├── price-stream/         # Price streaming
│           ├── live-stream/          # Live data streaming
│           ├── auth/                 # Authentication
│           ├── notification/         # Toast notifications
│           └── http.interceptor.ts   # HTTP interceptor
├── prediction-service/               # Standalone ML microservice (port 8010)
│   ├── app/
│   │   ├── api/                      # FastAPI routes (health, predict, models, market)
│   │   ├── core/                     # Settings, logging, Prometheus metrics
│   │   ├── db/                       # 9 SQLAlchemy models, async session
│   │   ├── features/                 # Market, options, macro, event, sentiment features
│   │   ├── inference/                # Predictor, regime router, confidence, SHAP
│   │   ├── ingestion/                # Historical loader, live stream, events, news
│   │   ├── models/                   # LightGBM, XGBoost, LSTM/GRU, regime, ensemble
│   │   ├── monitoring/               # PSI drift detection
│   │   ├── providers/                # Angel One, Yahoo, Mock + factory
│   │   ├── services/                 # Market session, model registry, Redis cache
│   │   ├── training/                 # Dataset builder, trainer, validation, walk-forward
│   │   └── main.py                   # FastAPI entry point
│   ├── tests/                        # 7 test modules
│   ├── Dockerfile
│   └── requirements.txt
├── models/                           # Model artifacts and registry
├── storage/                          # Raw CSV data (52 NSE tickers), backtest results
├── notebooks/                        # Jupyter exploration notebooks
├── infra/                            # K8s manifests, Helm charts, Grafana dashboards
├── docs/                             # API spec, features, options model card, runbooks
├── docker-compose.dev.yml            # Dev: API + Frontend + Postgres + Redis + Celery
├── docker-compose.prod.yml           # Production compose
├── docker-compose.microservices.yml  # Microservices mode (backend + prediction-service)
├── docker-compose.microservices.prod.yml
├── Dockerfile
├── requirements.txt
├── render.yaml                       # Render.com deployment config
├── DEPLOY.md                         # Deployment guide
└── .github/workflows/                # CI (lint + test) and CD (build + deploy)
```

## Features

- **Multi-model ensemble** -- LightGBM + XGBoost + LSTM with stacked meta-learner and isotonic calibration
- **Option trading** -- CE/PE signals, Greeks estimation, IV surfaces, vertical spreads, iron condors, covered calls
- **Paper trading** -- INR 100,000 default accounts, simulated fills with slippage, day/range replay
- **Portfolio analytics** -- Real-time portfolio dashboard, P&L tracking, sector allocation
- **Risk management** -- Position limits, VaR, stress testing, Greeks-based risk, drawdown monitoring
- **Auto-trading bot** -- Configurable bot with strategy rules, auto-execution, and lifecycle management
- **Market regime detection** -- Trending/mean-reverting/volatile regime classification for adaptive strategies
- **SHAP explainability** -- Top-5 feature contributions per prediction
- **Live streaming** -- WebSocket + SSE price feeds with reconnection and ticker tape
- **Drift detection** -- KS test + PSI on features and labels with automated alerting
- **Canary deployment** -- Shadow inference, A/B evaluation, promotion rules
- **MLflow integration** -- Model versioning, metrics tracking, artifact storage
- **Scheduled retrain** -- Celery-based nightly retrain with gating rules
- **News sentiment** -- Real-time news ingestion with keyword-based sentiment scoring
- **Prediction microservice** -- Standalone FastAPI service with dedicated ML pipeline, monitoring, and API
- **52 NSE tickers** -- Pre-downloaded historical data via yfinance (RELIANCE, TCS, INFY, HDFCBANK, etc.)

## Prerequisites

- **Python 3.11+**
- **Node.js 20+** (for Angular frontend)
- **Docker & Docker Compose** (optional, for containerised dev)

## Quick Start

### 1. Clone & configure environment variables

```bash
cp .env.example .env        # edit values as needed
```

### 2a. Run with Docker (recommended)

```bash
docker-compose -f docker-compose.dev.yml up --build
```

- Backend API: **http://localhost:8000** (Swagger: `/docs`)
- Frontend: **http://localhost:4200**

### 2b. Run locally (without Docker)

```bash
# Backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn backend.api.main:app --reload

# Frontend
cd frontend
npm install
npx ng serve

# Prediction Service (optional standalone)
cd prediction-service
pip install -r requirements.txt
uvicorn app.main:app --port 8010
```

### 3. Verify

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","service":"StockTrader","model_loaded":true}
```

## Running Tests

```bash
# Backend
pytest backend/tests/ -v

# Prediction service
cd prediction-service && pytest tests/ -v
```

## API Endpoints

All backend endpoints live under `/api/v1`. The prediction-service runs separately on port 8010.

### Backend API (port 8000)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/predict` | Single-ticker equity prediction |
| POST | `/predict/options` | Option signal with Greeks |
| POST | `/batch_predict` | Multi-ticker batch prediction |
| GET | `/model/status` | Current model info |
| POST | `/model/reload` | Hot-reload a model version |
| POST | `/retrain` | Trigger model retraining |
| GET | `/retrain/status` | Retrain job status |
| POST | `/backtest/run` | Launch a backtest job |
| GET | `/backtest/{job_id}/results` | Retrieve backtest results |
| POST | `/trade_intent` | Generate trading intent |
| POST | `/execute` | Execute an order (paper/live) |
| POST | `/paper/accounts` | Create paper account |
| GET | `/paper/accounts` | List paper accounts |
| GET | `/paper/{id}/equity` | Get equity curve |
| GET | `/paper/{id}/metrics` | Get account metrics |
| POST | `/paper/{id}/order_intent` | Submit order intent |
| POST | `/paper/{id}/replay` | Run day replay |
| GET | `/portfolio/dashboard` | Portfolio overview |
| GET | `/risk/dashboard` | Risk metrics & limits |
| GET | `/strategy/signals` | Active strategy signals |
| GET | `/market/session` | NSE session state |
| GET | `/market/regime` | Current market regime |
| WS | `/stream/price/{symbol}` | Live price WebSocket |
| GET | `/stream/price/{symbol}` | Live price SSE fallback |
| GET | `/stream/last_close/{symbol}` | Last closing price |
| GET | `/metrics` | Prometheus metrics export |
| GET | `/registry/versions` | List model versions |
| GET | `/registry/mlflow` | MLflow model metadata |
| POST | `/drift/check` | Run drift detection |
| GET | `/canary/status` | Canary deployment status |

### Prediction Service API (port 8010)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/health/ready` | Readiness probe |
| GET | `/api/v1/status` | Service status |
| GET | `/api/v1/metrics` | Prometheus metrics |
| POST | `/api/v1/predict` | Single prediction |
| POST | `/api/v1/predict/batch` | Batch predictions |
| GET | `/api/v1/predict/{symbol}` | GET-based prediction |
| POST | `/api/v1/models/train` | Trigger training |
| GET | `/api/v1/models/train/status` | Training status |
| GET | `/api/v1/models/active` | Active model info |
| GET | `/api/v1/models/list` | List model versions |
| POST | `/api/v1/models/promote/{v}` | Promote model |
| GET | `/api/v1/market-session` | NSE market session |
| GET | `/api/v1/events/active` | Active events |
| POST | `/api/v1/events/ingest` | Ingest event |
| GET | `/api/v1/drift` | Drift report |

See [docs/api_spec.md](docs/api_spec.md) for full request/response schemas.

## Training Pipeline

```bash
# 1. Download historical data (52 NSE tickers, auto-downloads on startup)
# Data stored in storage/raw/*.csv

# 2. Train via API
curl -X POST http://localhost:8000/api/v1/retrain -H "Content-Type: application/json" -d '{}'

# 3. Or train via prediction-service
curl -X POST http://localhost:8010/api/v1/models/train -H "Content-Type: application/json" \
  -d '{"model_type": "lightgbm"}'
```

The trainer uses walk-forward cross-validation with temporal splits (70/15/15) and embargo gaps to prevent data leakage. Artifacts are saved to `models/artifacts/` (backend) or `storage/models/` (prediction-service).

## CI/CD

- **CI** (`.github/workflows/ci.yml`): flake8 lint + pytest on every push/PR to `main`
- **CD** (`.github/workflows/cd.yml`): Docker build, push, deploy to staging on merge to `main`

## Deployment

```bash
# Development
docker-compose -f docker-compose.dev.yml up --build

# Production
docker-compose -f docker-compose.prod.yml up -d

# Microservices mode
docker-compose -f docker-compose.microservices.yml up -d

# Kubernetes
kubectl apply -f infra/k8s/

# Helm
helm install stocktrader infra/helm/stocktrader/
```

See [DEPLOY.md](DEPLOY.md) and [docs/runbooks.md](docs/runbooks.md) for operational procedures.

## Developer Guide

| Area | Location | Notes |
|------|----------|-------|
| Add a backend endpoint | `backend/api/routers/` | Create router, include in `main.py` |
| Add a schema | `backend/api/schemas.py` | Pydantic `BaseModel` |
| Add a feature | `backend/prediction_engine/feature_store/transforms.py` | Pure function, register in `FEATURE_COLUMNS` |
| Add a DB model | `backend/db/models.py` | SQLAlchemy declarative with `Base` |
| Add a service | `backend/services/` | Import into routers |
| Add a frontend page | `frontend/src/app/pages/` | Angular standalone component + route in `app.routes.ts` |
| Add a frontend service | `frontend/src/app/services/` | Injectable service, wire in components |
| Add a prediction feature | `prediction-service/app/features/` | Add to `feature_pipeline.py` |
| Add a test | `backend/tests/` or `prediction-service/tests/` | Prefix with `test_`, use fixtures |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Postgres connection string | SQLite fallback (`stocktrader.db`) |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | `*` |
| `SECRET_KEY` | App secret key | -- |
| `APP_ENV` | `development` / `production` | `development` |
| `PAPER_MODE` | Enable paper trading | `true` |
| `MLFLOW_TRACKING_URI` | MLflow server URL | `mlruns` |
| `NEWS_API_KEY` | NewsAPI key for sentiment | -- |
| `ANGEL_API_KEY` | Angel One broker API key | -- |
| `ANGEL_CLIENT_ID` | Angel One client ID | -- |
| `SENTRY_DSN` | Sentry error monitoring DSN | -- |
| `CELERY_BROKER_URL` | Celery broker (Redis) | `redis://localhost:6379/1` |
# stockTrader
