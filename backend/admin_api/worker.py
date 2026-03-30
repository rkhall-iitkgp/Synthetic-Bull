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
                last_commit = datetime.now()

                while True:
                    msg = await websocket.recv()
                    data = json.loads(msg)

                    if data.get("type") == "trade":
                        await broadcast_to_clients(data)

                        trade = models.Trade(
                            id=str(data["id"]),
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
                            id=str(data["id"]) + "_sell",
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

                    # Simple batching every 10 items or 2 seconds
                    if len(batch) >= 10 or (datetime.now() - last_commit).seconds >= 2:
                        if batch:
                            try:
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
