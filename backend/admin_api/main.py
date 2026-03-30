import uuid
import secrets
import asyncio
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

import models, schemas
from database import engine, get_db
from worker import logger_worker, deposit_queue

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Synthetic Bull - Admin API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: List[WebSocket] = []

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(logger_worker())

def generate_api_key():
    return f"sk_live_{secrets.token_hex(16)}"

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.post("/api/bots", response_model=schemas.BotResponse)
def create_bot(bot: schemas.BotCreate, db: Session = Depends(get_db)):
    api_key = generate_api_key()
    
    db_bot = models.Bot(name=bot.name, api_key=api_key)
    db.add(db_bot)
    db.commit()
    db.refresh(db_bot)
    
    # Initialize portfolio
    db_portfolio = models.Portfolio(bot_id=db_bot.id, cash_balance=100000.0)
    db.add(db_portfolio)
    db.commit()
    
    return db_bot

@app.get("/api/bots", response_model=List[schemas.BotResponse])
def get_bots(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    bots = db.query(models.Bot).offset(skip).limit(limit).all()
    return bots

@app.get("/api/bots/{bot_id}/trades", response_model=List[schemas.TradeResponse])
def get_bot_trades(bot_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
        
    trades = db.query(models.Trade).filter(models.Trade.bot_id == bot_id).order_by(models.Trade.timestamp.desc()).offset(skip).limit(limit).all()
    return trades

@app.get("/api/bots/{bot_id}/portfolio")
def get_bot_portfolio(bot_id: str, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
        
    # Compute portfolio dynamically from trades
    trades = db.query(models.Trade).filter(models.Trade.bot_id == bot_id).all()

    portfolio_record = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    initial_capital = (portfolio_record.initial_capital if portfolio_record and portfolio_record.initial_capital else 100000.0)
    cash_balance = initial_capital
    positions = {}

    for t in trades:
        value = t.price * t.qty
        if t.side == "buy" or t.side == "BUY":
            cash_balance -= value
            positions[t.symbol] = positions.get(t.symbol, 0) + t.qty
        else:
            cash_balance += value
            positions[t.symbol] = positions.get(t.symbol, 0) - t.qty

    position_list = []
    for sym, qty in positions.items():
        if round(qty, 6) != 0:
            position_list.append({"symbol": sym, "qty": qty, "avg_entry_price": 0.0})

    return {
        "cash_balance": round(cash_balance, 2),
        "initial_capital": round(initial_capital, 2),
        "positions": position_list
    }

@app.post("/api/bots/{bot_id}/deposit", response_model=schemas.DepositResponse)
async def deposit_funds(bot_id: str, req: schemas.DepositRequest, db: Session = Depends(get_db)):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Update initial_capital (the base for dynamic cash computation)
    portfolio.initial_capital = (portfolio.initial_capital or 100000.0) + req.amount
    db.commit()
    db.refresh(portfolio)

    # Notify the C++ engine to update in-memory portfolio
    await deposit_queue.put({"bot_id": bot_id, "amount": req.amount})

    # Recompute current cash for response
    trades = db.query(models.Trade).filter(models.Trade.bot_id == bot_id).all()
    cash = portfolio.initial_capital
    for t in trades:
        value = t.price * t.qty
        if t.side in ("buy", "BUY"):
            cash -= value
        else:
            cash += value

    return schemas.DepositResponse(
        bot_id=bot_id,
        amount=req.amount,
        new_cash_balance=round(cash, 2)
    )
