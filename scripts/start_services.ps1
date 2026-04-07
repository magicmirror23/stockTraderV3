# Start all microservices for local development (Windows PowerShell)
# Usage:
#   .\scripts\start_services.ps1           # stable mode (no auto-reload)
#   .\scripts\start_services.ps1 -Reload   # enable auto-reload

param(
    [switch]$Reload
)

Write-Host "Starting StockTrader microservices..." -ForegroundColor Cyan
Write-Host "============================================"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

if ($PythonExe -eq "python") {
    Write-Host "WARNING: .venv Python not found. Falling back to 'python' from PATH." -ForegroundColor Yellow
}
else {
    Write-Host "Using Python: $PythonExe" -ForegroundColor DarkCyan
}

$ReloadArgs = @()
if ($Reload.IsPresent) {
    $ReloadArgs = @("--reload")
    Write-Host "Auto-reload mode: ON" -ForegroundColor DarkYellow
}
else {
    Write-Host "Auto-reload mode: OFF (stable startup)" -ForegroundColor DarkGreen
}

$GATEWAY_PORT = 8000
$MARKET_PORT = 8001
$PREDICTION_PORT = 8002
$TRADING_PORT = 8003
$ADMIN_PORT = 8004
$INTRADAY_FEATURES_PORT = 8005
$INTRADAY_PREDICTION_PORT = 8006
$OPTIONS_SIGNAL_PORT = 8007
$EXECUTION_ENGINE_PORT = 8008
$TRADE_SUPERVISOR_PORT = 8009

# Export service URLs for gateway
$env:MARKET_DATA_URL = "http://localhost:$MARKET_PORT"
$env:PREDICTION_URL = "http://localhost:$PREDICTION_PORT"
$env:TRADING_URL = "http://localhost:$TRADING_PORT"
$env:ADMIN_URL = "http://localhost:$ADMIN_PORT"
$env:INTRADAY_FEATURES_URL = "http://localhost:$INTRADAY_FEATURES_PORT"
$env:INTRADAY_PREDICTION_URL = "http://localhost:$INTRADAY_PREDICTION_PORT"
$env:OPTIONS_SIGNAL_URL = "http://localhost:$OPTIONS_SIGNAL_PORT"
$env:EXECUTION_ENGINE_URL = "http://localhost:$EXECUTION_ENGINE_PORT"
$env:TRADE_SUPERVISOR_URL = "http://localhost:$TRADE_SUPERVISOR_PORT"

$jobs = @()

Write-Host "[1/10] Starting Market Data service on port $MARKET_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.market_data:app", "--host", "0.0.0.0", "--port", "$MARKET_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[2/10] Starting Prediction service on port $PREDICTION_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.prediction:app", "--host", "0.0.0.0", "--port", "$PREDICTION_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[3/10] Starting Trading service on port $TRADING_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.trading:app", "--host", "0.0.0.0", "--port", "$TRADING_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[4/10] Starting Admin/Backtest service on port $ADMIN_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.admin_backtest:app", "--host", "0.0.0.0", "--port", "$ADMIN_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[5/10] Starting API Gateway on port $GATEWAY_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.gateway:app", "--host", "0.0.0.0", "--port", "$GATEWAY_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[6/10] Starting Intraday Features service on port $INTRADAY_FEATURES_PORT..." -ForegroundColor Magenta
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.intraday_features:app", "--host", "0.0.0.0", "--port", "$INTRADAY_FEATURES_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[7/10] Starting Intraday Prediction service on port $INTRADAY_PREDICTION_PORT..." -ForegroundColor Magenta
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.intraday_prediction:app", "--host", "0.0.0.0", "--port", "$INTRADAY_PREDICTION_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[8/10] Starting Options Signal service on port $OPTIONS_SIGNAL_PORT..." -ForegroundColor Magenta
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.options_signal:app", "--host", "0.0.0.0", "--port", "$OPTIONS_SIGNAL_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[9/10] Starting Execution Engine service on port $EXECUTION_ENGINE_PORT..." -ForegroundColor Magenta
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.execution_engine:app", "--host", "0.0.0.0", "--port", "$EXECUTION_ENGINE_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host "[10/10] Starting Trade Supervisor service on port $TRADE_SUPERVISOR_PORT..." -ForegroundColor Magenta
$jobs += Start-Process -FilePath $PythonExe `
    -ArgumentList (@("-m", "uvicorn", "backend.api.services.trade_supervisor:app", "--host", "0.0.0.0", "--port", "$TRADE_SUPERVISOR_PORT") + $ReloadArgs) `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "All services started!" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Gateway:              http://localhost:$GATEWAY_PORT"
Write-Host "  Market Data:          http://localhost:$MARKET_PORT"
Write-Host "  Prediction:           http://localhost:$PREDICTION_PORT"
Write-Host "  Trading:              http://localhost:$TRADING_PORT"
Write-Host "  Admin:                http://localhost:$ADMIN_PORT"
Write-Host ""
Write-Host "  --- Intraday Stack ---" -ForegroundColor Magenta
Write-Host "  Intraday Features:    http://localhost:$INTRADAY_FEATURES_PORT"
Write-Host "  Intraday Prediction:  http://localhost:$INTRADAY_PREDICTION_PORT"
Write-Host "  Options Signal:       http://localhost:$OPTIONS_SIGNAL_PORT"
Write-Host "  Execution Engine:     http://localhost:$EXECUTION_ENGINE_PORT"
Write-Host "  Trade Supervisor:     http://localhost:$TRADE_SUPERVISOR_PORT"
Write-Host ""
Write-Host "Press Ctrl+C to stop all services." -ForegroundColor Yellow
Write-Host "============================================"

try {
    # Keep script running
    while ($true) {
        Start-Sleep -Seconds 1
        # Check if any process has exited
        foreach ($job in $jobs) {
            if ($job.HasExited) {
                Write-Host "WARNING: Process $($job.Id) exited with code $($job.ExitCode)" -ForegroundColor Red
            }
        }
    }
} finally {
    Write-Host "Stopping all services..." -ForegroundColor Yellow
    foreach ($job in $jobs) {
        if (-not $job.HasExited) {
            Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "All services stopped." -ForegroundColor Green
}
