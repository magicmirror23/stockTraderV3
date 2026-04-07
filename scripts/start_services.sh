#!/usr/bin/env bash
# Start all microservices for local development (without Docker)
# Usage:
#   bash scripts/start_services.sh           # stable mode (no auto-reload)
#   bash scripts/start_services.sh --reload  # enable auto-reload

set -e

echo "Starting StockTrader microservices..."
echo "============================================"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
PIDS=()
RELOAD_ARGS=()

if [[ "${1:-}" == "--reload" ]]; then
  RELOAD_ARGS=(--reload)
  echo "Auto-reload mode: ON"
else
  echo "Auto-reload mode: OFF (stable startup)"
fi

if [[ -x "$VENV_PYTHON" ]]; then
  PYTHON_BIN="$VENV_PYTHON"
else
  PYTHON_BIN="python3"
  echo "WARNING: .venv Python not found. Falling back to $PYTHON_BIN from PATH."
fi

# Ports
GATEWAY_PORT=8000
MARKET_PORT=8001
PREDICTION_PORT=8002
TRADING_PORT=8003
ADMIN_PORT=8004

# Export service URLs for the gateway
export MARKET_DATA_URL="http://localhost:${MARKET_PORT}"
export PREDICTION_URL="http://localhost:${PREDICTION_PORT}"
export TRADING_URL="http://localhost:${TRADING_PORT}"
export ADMIN_URL="http://localhost:${ADMIN_PORT}"

# Start each service in the background
echo "[1/5] Starting Market Data service on port ${MARKET_PORT}..."
(cd "$PROJECT_ROOT" && "$PYTHON_BIN" -m uvicorn backend.api.services.market_data:app --host 0.0.0.0 --port ${MARKET_PORT} "${RELOAD_ARGS[@]}") &
PIDS+=($!)

echo "[2/5] Starting Prediction service on port ${PREDICTION_PORT}..."
(cd "$PROJECT_ROOT" && "$PYTHON_BIN" -m uvicorn backend.api.services.prediction:app --host 0.0.0.0 --port ${PREDICTION_PORT} "${RELOAD_ARGS[@]}") &
PIDS+=($!)

echo "[3/5] Starting Trading service on port ${TRADING_PORT}..."
(cd "$PROJECT_ROOT" && "$PYTHON_BIN" -m uvicorn backend.api.services.trading:app --host 0.0.0.0 --port ${TRADING_PORT} "${RELOAD_ARGS[@]}") &
PIDS+=($!)

echo "[4/5] Starting Admin/Backtest service on port ${ADMIN_PORT}..."
(cd "$PROJECT_ROOT" && "$PYTHON_BIN" -m uvicorn backend.api.services.admin_backtest:app --host 0.0.0.0 --port ${ADMIN_PORT} "${RELOAD_ARGS[@]}") &
PIDS+=($!)

echo "[5/5] Starting API Gateway on port ${GATEWAY_PORT}..."
(cd "$PROJECT_ROOT" && "$PYTHON_BIN" -m uvicorn backend.api.services.gateway:app --host 0.0.0.0 --port ${GATEWAY_PORT} "${RELOAD_ARGS[@]}") &
PIDS+=($!)

echo ""
echo "============================================"
echo "All services started!"
echo ""
echo "  Gateway:       http://localhost:${GATEWAY_PORT}"
echo "  Market Data:   http://localhost:${MARKET_PORT}"
echo "  Prediction:    http://localhost:${PREDICTION_PORT}"
echo "  Trading:       http://localhost:${TRADING_PORT}"
echo "  Admin:         http://localhost:${ADMIN_PORT}"
echo ""
echo "Press Ctrl+C to stop all services."
echo "============================================"

# Trap SIGINT to kill all background processes
trap 'echo "Stopping all services..."; kill ${PIDS[@]} 2>/dev/null; exit 0' SIGINT SIGTERM

# Wait for all background processes
wait
