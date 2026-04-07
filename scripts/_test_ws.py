"""End-to-end test: verify WebSocket streams work from both gateway and direct."""
import asyncio
import json
import websockets

async def test_ws(label, uri):
    try:
        async with websockets.connect(uri, open_timeout=5) as ws:
            await ws.send(json.dumps({"action": "subscribe", "symbols": ["RELIANCE", "TCS"]}))
            ticks = []
            for _ in range(4):
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                d = json.loads(msg)
                ticks.append(d)
            prices = set()
            for t in ticks:
                prices.add(f"{t['symbol']}={t['price']}")
            print(f"  [{label}] OK - {len(ticks)} ticks: {', '.join(sorted(prices))}")
            rel_prices = [t['price'] for t in ticks if t['symbol'] == 'RELIANCE']
            mode = ticks[0].get('feed_mode', '?')
            print(f"    feed_mode={mode}, RELIANCE prices: {rel_prices}")
            return True
    except Exception as e:
        print(f"  [{label}] FAILED: {type(e).__name__}: {e}")
        return False

async def main():
    print("Testing WebSocket streaming endpoints...\n")
    ok1 = await test_ws("Direct:8001", "ws://localhost:8001/api/v1/stream/multi")
    ok2 = await test_ws("Gateway:8000", "ws://localhost:8000/api/v1/stream/multi")
    print(f"\nResults: Direct={'PASS' if ok1 else 'FAIL'}, Gateway={'PASS' if ok2 else 'FAIL'}")

asyncio.run(main())
