import asyncio
import json
import os
import websockets
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import dateutil.parser
import models
from database import SessionLocal

MASTER_API_KEY = "sk_admin_12345"
WS_URL = os.getenv("ENGINE_WS_URL", "ws://localhost:9001")

# Shared queue for deposit requests from the API endpoint
deposit_queue = asyncio.Queue()

async def broadcast_to_clients(data):
    from main import active_connections
    for conn in active_connections:
        try:
            await conn.send_json(data)
        except:
            pass

async def logger_worker():
    while True:
        try:
            print(f"[Worker] Connecting to engine at {WS_URL}...")
            async with websockets.connect(WS_URL) as websocket:
                # Auth as admin
                await websocket.send(json.dumps({
                    "type": "auth",
                    "api_key": MASTER_API_KEY
                }))

                auth_resp = await websocket.recv()
                print(f"[Worker] Auth response: {auth_resp}")

                db = SessionLocal()

                # Batch processing
                batch = []
                seen_trades = set()
                last_commit = datetime.now()

                while True:
                    try:
                        msg = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(msg)

                        if data.get("type") == "trade":
                            trade_id = f"{data['symbol']}_{data['id']}"
                            if trade_id in seen_trades:
                                continue
                            seen_trades.add(trade_id)
                            
                            # Prevent memory leak over days
                            if len(seen_trades) > 5000:
                                seen_trades.clear()

                            await broadcast_to_clients(data)

                            trade = models.Trade(
                                id=trade_id + "_buy",
                                bot_id=data["buyer"],  # We record buyer and seller?
                                # The spec says trade needs bot_id, but a trade has a buyer and a seller.
                                # We can insert two records or adjust Schema. Let's insert two for PnL tracking, or just update the portfolio.
                                symbol=data["symbol"],
                                side="buy", # this is relative to 'buyer'       
                                price=data["price"],
                                qty=data["qty"],
                                timestamp=datetime.fromtimestamp(data["ts"] / 1000000.0, tz=timezone.utc)
                            )
                            trade2 = models.Trade(
                                id=trade_id + "_sell",
                                bot_id=data["seller"],
                                symbol=data["symbol"],
                                side="sell",
                                price=data["price"],
                                qty=data["qty"],
                                timestamp=datetime.fromtimestamp(data["ts"] / 1000000.0, tz=timezone.utc)
                            )

                            # Only add trades for real bots, ignore "sim_bot"   
                            if data["buyer"] != "sim_bot":
                                batch.append(trade)
                            if data["seller"] != "sim_bot":
                                batch.append(trade2)

                    except asyncio.TimeoutError:
                        pass # Proceed to flush

                    # Forward any pending deposit requests to the C++ engine
                    while not deposit_queue.empty():
                        try:
                            dep = deposit_queue.get_nowait()
                            await websocket.send(json.dumps({
                                "type": "deposit",
                                "bot_id": dep["bot_id"],
                                "amount": dep["amount"]
                            }))
                            print(f"[Worker] Forwarded deposit: {dep['amount']} to bot {dep['bot_id']}")
                        except asyncio.QueueEmpty:
                            break
                        except Exception as e:
                            print(f"[Worker] Failed to forward deposit: {e}")

                    # Simple batching every 10 items or 2 seconds
                    if len(batch) >= 10 or (batch and (datetime.now() - last_commit).seconds >= 2):
                        if batch:
                            try:
                                print(f"[Worker] Committing batch of {len(batch)} trades...")
                                for b in batch:
                                    print(f"  - {b.id} | bot: {b.bot_id} | side: {b.side} | qty: {b.qty}")
                                db.bulk_save_objects(batch)
                                db.commit()
                            except Exception as e:
                                db.rollback()
                                print(f"[Worker] Db error: {e}")
                            batch = []
                        last_commit = datetime.now()
        except Exception as e:
            print(f"[Worker] Disconnected from engine: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(logger_worker())
