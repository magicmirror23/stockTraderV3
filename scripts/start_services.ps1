# Start all microservices for local development (Windows PowerShell)
# Usage: .\scripts\start_services.ps1

Write-Host "Starting StockTrader microservices..." -ForegroundColor Cyan
Write-Host "============================================"

$GATEWAY_PORT = 8000
$MARKET_PORT = 8001
$PREDICTION_PORT = 8002
$TRADING_PORT = 8003
$ADMIN_PORT = 8004

# Export service URLs for gateway
$env:MARKET_DATA_URL = "http://localhost:$MARKET_PORT"
$env:PREDICTION_URL = "http://localhost:$PREDICTION_PORT"
$env:TRADING_URL = "http://localhost:$TRADING_PORT"
$env:ADMIN_URL = "http://localhost:$ADMIN_PORT"

$jobs = @()

Write-Host "[1/5] Starting Market Data service on port $MARKET_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath "uvicorn" `
    -ArgumentList "backend.api.services.market_data:app", "--host", "0.0.0.0", "--port", "$MARKET_PORT", "--reload" `
    -PassThru -NoNewWindow

Write-Host "[2/5] Starting Prediction service on port $PREDICTION_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath "uvicorn" `
    -ArgumentList "backend.api.services.prediction:app", "--host", "0.0.0.0", "--port", "$PREDICTION_PORT", "--reload" `
    -PassThru -NoNewWindow

Write-Host "[3/5] Starting Trading service on port $TRADING_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath "uvicorn" `
    -ArgumentList "backend.api.services.trading:app", "--host", "0.0.0.0", "--port", "$TRADING_PORT", "--reload" `
    -PassThru -NoNewWindow

Write-Host "[4/5] Starting Admin/Backtest service on port $ADMIN_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath "uvicorn" `
    -ArgumentList "backend.api.services.admin_backtest:app", "--host", "0.0.0.0", "--port", "$ADMIN_PORT", "--reload" `
    -PassThru -NoNewWindow

Write-Host "[5/5] Starting API Gateway on port $GATEWAY_PORT..." -ForegroundColor Green
$jobs += Start-Process -FilePath "uvicorn" `
    -ArgumentList "backend.api.services.gateway:app", "--host", "0.0.0.0", "--port", "$GATEWAY_PORT", "--reload" `
    -PassThru -NoNewWindow

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "All services started!" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Gateway:       http://localhost:$GATEWAY_PORT"
Write-Host "  Market Data:   http://localhost:$MARKET_PORT"
Write-Host "  Prediction:    http://localhost:$PREDICTION_PORT"
Write-Host "  Trading:       http://localhost:$TRADING_PORT"
Write-Host "  Admin:         http://localhost:$ADMIN_PORT"
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
