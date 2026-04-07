"""Quick data freshness verification script."""
import requests
import json

print("=== MARKET DATA (port 8001) ===")
d = requests.get("http://localhost:8001/api/v1/stream/market-overview", timeout=10).json()
g = d.get("gainers", [])
if g:
    print(f"  Gainers: {len(g)}, Top: {g[0]['symbol']} +{g[0]['change_pct']}%")
    print(f"  Timestamp: {g[0]['timestamp']}")
else:
    print("  No gainers")

print()
print("=== PREDICTION ENGINE (port 8002) ===")
p = requests.post("http://localhost:8002/api/v1/predict", json={"ticker": "TCS"}, timeout=15).json()
pred = p.get("prediction", {})
print(f"  TCS: action={pred.get('action')}, confidence={p.get('confidence')}, model={p.get('model_version')}")
print(f"  Timestamp: {p.get('timestamp')}")

print()
print("=== TRADING BOT (port 8003) ===")
b = requests.get("http://localhost:8003/api/v1/bot/status", timeout=5).json()
print(f"  State: {b['state']}, Watchlist: {b['config']['watchlist']}")

print()
print("=== FEED STATUS ===")
f = requests.get("http://localhost:8001/api/v1/stream/feed-status", timeout=5).json()
print(f"  Mode: {f['feed_mode']}, Market: {f['market_phase']}, Open: {f['is_market_open']}")

print()
print("=== GATEWAY PROXY (port 8000) ===")
gw = requests.get("http://localhost:8000/api/v1/stream/market-overview", timeout=10).json()
gw_g = gw.get("gainers", [])
if gw_g:
    print(f"  Via Gateway - Timestamp: {gw_g[0]['timestamp']}")
else:
    print("  Via Gateway - No data")

print()
print("=== ALL SERVICES HEALTH ===")
for port, name in [(8000, "Gateway"), (8001, "Market Data"), (8002, "Prediction"),
                    (8003, "Trading"), (8004, "Admin"), (8005, "Intraday Features"),
                    (8006, "Intraday Prediction"), (8007, "Options Signal"),
                    (8008, "Execution Engine"), (8009, "Trade Supervisor")]:
    try:
        r = requests.get(f"http://localhost:{port}/api/v1/health", timeout=3)
        status = r.json().get("status", "unknown")
        print(f"  {name} ({port}): {status}")
    except Exception as e:
        print(f"  {name} ({port}): ERROR - {e}")
