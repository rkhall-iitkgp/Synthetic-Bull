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

def process_trade_fifo(db: Session, trade: models.Trade):
    # Find active sessions to attribute PnL
    active_sessions = db.query(models.BotSession).filter(
        models.BotSession.bot_id == trade.bot_id,
        models.BotSession.status == "active"
    ).all()
    
    # Assign session_id to the trade if it's part of a lap, or fallback to connection
    lap = next((s for s in active_sessions if s.session_type == "lap"), None)
    conn = next((s for s in active_sessions if s.session_type == "connection"), None)
    if lap:
        trade.session_id = lap.id
        trade.run_id = lap.run_id
    elif conn:
        trade.session_id = conn.id
        trade.run_id = conn.run_id
        
    opp_side = "sell" if trade.side == "buy" else "buy"
    
    # Get previous open trades to match against
    open_ops = db.query(models.Trade).filter(
        models.Trade.bot_id == trade.bot_id,
        models.Trade.symbol == trade.symbol,
        models.Trade.side == opp_side,
        models.Trade.unclosed_qty > 0
    ).order_by(models.Trade.timestamp.asc()).all()

    for opp in open_ops:
        if trade.unclosed_qty <= 0:
            break
            
        match_qty = min(trade.unclosed_qty, opp.unclosed_qty)
        trade.unclosed_qty -= match_qty
        opp.unclosed_qty -= match_qty
        
        # Calculate PnL
        if trade.side == "buy": # Covering a short
            pnl = (opp.price - trade.price) * match_qty
            pct = 0.0 if opp.price == 0 else (opp.price - trade.price) / opp.price
            side_label = "short"
        else: # Closing a long
            pnl = (trade.price - opp.price) * match_qty
            pct = 0.0 if opp.price == 0 else (trade.price - opp.price) / opp.price
            side_label = "long"
            
        rnd = models.TradeRound(
            bot_id=trade.bot_id,
            session_id=trade.session_id,
            run_id=trade.run_id,
            symbol=trade.symbol,
            side=side_label,
            entry_price=opp.price,
            exit_price=trade.price,
            qty=match_qty,
            pnl=pnl,
            pct_return=pct
        )
        db.add(rnd)
        
        # Add realized PnL to all active sessions
        for s in active_sessions:
            s.realized_pnl += pnl

    db.add(trade)
    
    # Update Position
    pos = db.query(models.Position).filter(
        models.Position.bot_id == trade.bot_id,
        models.Position.symbol == trade.symbol
    ).first()
    if not pos:
        pos = models.Position(bot_id=trade.bot_id, symbol=trade.symbol, qty=0.0, avg_entry_price=0.0)
        db.add(pos)
        
    old_qty = pos.qty
    trade_sign = 1.0 if trade.side == "buy" else -1.0
    new_qty = old_qty + (trade.qty * trade_sign)
    
    # If adding to position, update avg entry price
    if abs(new_qty) > abs(old_qty) and (old_qty * trade_sign >= 0):  # Same direction
        total_value = abs(old_qty) * pos.avg_entry_price + trade.qty * trade.price
        pos.avg_entry_price = total_value / abs(new_qty) if new_qty != 0 else 0.0
    elif new_qty == 0:
        pos.avg_entry_price = 0.0
        pos.unrealized_pnl = 0.0
        
    pos.qty = new_qty

def update_market_price(db: Session, symbol: str, current_price: float):
    """
    Updates the unrealized PnL for all bots holding this symbol,
    then updates the high/low equity marks for their active sessions.
    """
    # 1. Update unrealized PnL for all active positions of this symbol
    positions = db.query(models.Position).filter(
        models.Position.symbol == symbol,
        models.Position.qty != 0
    ).all()
    
    if not positions:
        return

    # Track which bots were affected so we only update their sessions
    affected_bot_ids = set()
    for pos in positions:
        pos.unrealized_pnl = pos.qty * (current_price - pos.avg_entry_price)
        affected_bot_ids.add(pos.bot_id)
        
    # 2. Update equity watermark for active sessions of affected bots
    active_sessions = db.query(models.BotSession).filter(
        models.BotSession.status == "active",
        models.BotSession.bot_id.in_(affected_bot_ids)
    ).all()
    
    for session in active_sessions:
        # Sum total unrealized pnl for this specific bot
        bot_positions = db.query(models.Position).filter(
            models.Position.bot_id == session.bot_id
        ).all()
        total_unrealized = sum(p.unrealized_pnl for p in bot_positions)
        
        current_equity = session.starting_equity + session.realized_pnl + total_unrealized
        
        if current_equity > session.max_equity:
            session.max_equity = current_equity
        if current_equity < session.min_equity:
            session.min_equity = current_equity

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
                                bot_id=data["buyer"],
                                symbol=data["symbol"],
                                side="buy",
                                price=data["price"],
                                qty=data["qty"],
                                unclosed_qty=data["qty"],
                                timestamp=datetime.fromtimestamp(data["ts"] / 1000000.0, tz=timezone.utc)
                            )
                            trade2 = models.Trade(
                                id=trade_id + "_sell",
                                bot_id=data["seller"],
                                symbol=data["symbol"],
                                side="sell",
                                price=data["price"],
                                qty=data["qty"],
                                unclosed_qty=data["qty"],
                                timestamp=datetime.fromtimestamp(data["ts"] / 1000000.0, tz=timezone.utc)
                            )

                            if data["buyer"] != "sim_bot":
                                process_trade_fifo(db, trade)
                                batch.append(trade)
                            if data["seller"] != "sim_bot":
                                process_trade_fifo(db, trade2)
                                batch.append(trade2)

                            # Trigger market price mark-to-market updates for tracking equity & drawdown
                            update_market_price(db, data["symbol"], data["price"])

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
