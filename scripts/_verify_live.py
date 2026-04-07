"""Verify live market data on all endpoints."""
import requests
import json

print("=== FEED STATUS ===")
r = requests.get("http://localhost:8001/api/v1/stream/feed-status", timeout=5)
f = r.json()
print(f"  Mode: {f['feed_mode']}, Connected: {f['connected']}, Ticks: {f['tick_count']}, Symbols: {f['symbols_streaming']}")

print("\n=== MARKET OVERVIEW ===")
r = requests.get("http://localhost:8001/api/v1/stream/market-overview", timeout=10)
d = r.json()
for label, key in [("Top Gainers", "gainers"), ("Top Losers", "losers")]:
    items = d.get(key, [])
    print(f"  {label}:")
    for s in items[:3]:
        print(f"    {s['symbol']}: Rs.{s['price']:.2f} ({s['change_pct']:+.2f}%) @ {s['timestamp']}")

print("\n=== LIVE PRICES ===")
for sym in ["RELIANCE", "TCS", "INFY", "HDFCBANK", "NIFTY50"]:
    r = requests.get(f"http://localhost:8001/api/v1/stream/last_close/{sym}", timeout=5)
    d = r.json()
    print(f"  {sym}: Rs.{d['price']:.2f} mode={d.get('feed_mode','?')} ts={d['timestamp']}")

print("\n=== GATEWAY PROXY ===")
r = requests.get("http://localhost:8000/api/v1/stream/feed-status", timeout=10)
g = r.json()
print(f"  Via Gateway: mode={g['feed_mode']}, connected={g['connected']}, ticks={g['tick_count']}")

print("\n=== ALL SERVICES HEALTH ===")
for port, name in [(8000, "Gateway"), (8001, "Market Data"), (8002, "Prediction"),
                    (8003, "Trading"), (8004, "Admin"), (8005, "Intraday Features"),
                    (8006, "Intraday Prediction"), (8007, "Options Signal"),
                    (8008, "Execution Engine"), (8009, "Trade Supervisor")]:
    try:
        r = requests.get(f"http://localhost:{port}/api/v1/health", timeout=3)
        print(f"  {name} ({port}): {r.json().get('status', '?')}")
    except Exception as e:
        print(f"  {name} ({port}): ERROR - {e}")
