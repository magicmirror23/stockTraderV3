"""Test Angel One live WebSocket feed."""
from dotenv import load_dotenv; load_dotenv()
from backend.services.angel_feed import AngelLiveFeed
import time

feed = AngelLiveFeed()
print("Connecting to AngelOne WebSocket...")
ok = feed.connect(["RELIANCE", "TCS", "INFY", "HDFCBANK"])
print("Connect OK:", ok)
print("Status:", feed.status)

if ok:
    print("Waiting 3s for ticks...")
    time.sleep(3)
    for sym in ["RELIANCE", "TCS", "INFY"]:
        tick = feed.get_latest(sym)
        if tick:
            print(f"  {sym}: price={tick['price']}, vol={tick['volume']}, ts={tick['timestamp']}")
        else:
            print(f"  {sym}: no ticks yet")
    print(f"Total ticks received: {feed.status['tick_count']}")
    feed.disconnect()
    print("Disconnected.")
else:
    print("ERROR:", feed.status.get("error"))
