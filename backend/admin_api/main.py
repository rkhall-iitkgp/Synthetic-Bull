import uuid
import secrets
import asyncio
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
import datetime

import models, schemas
from database import engine, get_db, SessionLocal
from sqlalchemy.sql import func
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

DEFAULT_ALPHA_API_KEY = "sk_live_2f55c85f1bf3f19535f4f8763c6bbc51"
DEFAULT_MM_API_KEY = "sk_live_1641719b61f46e9efe1a543ee948307b"

def seed_database(db: Session):
    alpha_bot = db.query(models.Bot).filter(models.Bot.api_key == DEFAULT_ALPHA_API_KEY).first()
    if not alpha_bot:
        db_bot = models.Bot(name="Alpha Bot", api_key=DEFAULT_ALPHA_API_KEY)
        db.add(db_bot)
        db.commit()
        db_portfolio = models.Portfolio(bot_id=db_bot.id, cash_balance=100000.0)
        db.add(db_portfolio)
        db.commit()

    mm_bot = db.query(models.Bot).filter(models.Bot.api_key == DEFAULT_MM_API_KEY).first()
    if not mm_bot:
        db_bot = models.Bot(name="Market Maker Bot", api_key=DEFAULT_MM_API_KEY)
        db.add(db_bot)
        db.commit()
        db_portfolio = models.Portfolio(bot_id=db_bot.id, cash_balance=100000.0)
        db.add(db_portfolio)
        db.commit()

@app.on_event("startup")
async def startup_event():
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    asyncio.create_task(logger_worker())

def generate_api_key():
    return f"sk_live_{secrets.token_hex(16)}"

@app.websocket("/ws/{bot_id}")
async def websocket_bot_endpoint(websocket: WebSocket, bot_id: str, db: Session = Depends(get_db)):
    await websocket.accept()
    
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        await websocket.close()
        return

    # Calculate starting equity
    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    starting_equity = portfolio.initial_capital if portfolio else 0.0

    # Start connection session
    session = models.BotSession(
        bot_id=bot_id,
        session_type="connection",
        starting_equity=starting_equity,
        max_equity=starting_equity,
        min_equity=starting_equity
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        session.status = "completed"
        session.end_time = func.now()
        db.commit()

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

@app.get("/api/bots/{bot_id}", response_model=schemas.BotResponse)
def get_bot(bot_id: str, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot

@app.get("/api/bots/{bot_id}/trades", response_model=List[schemas.TradeResponse])
def get_bot_trades(
    bot_id: str,
    skip: int = 0,
    limit: int = 100,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    query = db.query(models.Trade).filter(models.Trade.bot_id == bot_id)
    if session_id:
        query = query.filter(models.Trade.session_id == session_id)

    trades = query.order_by(models.Trade.timestamp.desc()).offset(skip).limit(limit).all()
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

@app.get("/api/bots/{bot_id}/kpi", response_model=schemas.BotKPIResponse)
def get_bot_kpi(bot_id: str, session_id: Optional[str] = None, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    import numpy as np

    if session_id:
        trade_rounds = db.query(models.TradeRound).filter(
            models.TradeRound.bot_id == bot_id,
            models.TradeRound.session_id == session_id
        ).all()
        session = db.query(models.BotSession).filter(
            models.BotSession.id == session_id,
            models.BotSession.bot_id == bot_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        max_eq = session.max_equity or 1.0
        min_eq = session.min_equity or 1.0
        drawdown = 0.0 if max_eq <= 0 else (max_eq - min_eq) / max_eq
    else:
        trade_rounds = db.query(models.TradeRound).filter(
            models.TradeRound.bot_id == bot_id
        ).all()

        # For overall drawdown, query the aggregated sessions.
        sessions = db.query(models.BotSession).filter(models.BotSession.bot_id == bot_id).all()
        if not sessions:
            drawdown = 0.0
        else:
            max_eq = max((s.max_equity for s in sessions if s.max_equity), default=1.0)
            min_eq = min((s.min_equity for s in sessions if s.min_equity), default=1.0)
            drawdown = 0.0 if max_eq <= 0 else (max_eq - min_eq) / max_eq

    # Realized PnL should come from closed trade rounds, not session aggregates.
    realized_pnl = float(sum(t.pnl for t in trade_rounds))

    total_trades = len(trade_rounds)
    win_rate = 0.0
    sharpe_ratio = 0.0

    if total_trades > 0:
        winning_trades = sum(1 for t in trade_rounds if t.pnl > 0)
        win_rate = winning_trades / total_trades
        
        returns = [t.pct_return for t in trade_rounds]
        std = np.std(returns, ddof=1) if len(returns) > 1 else 0.0
        if std > 0:
            mean_ret = np.mean(returns)
            sharpe_ratio = (mean_ret / std) * np.sqrt(len(returns))

    return schemas.BotKPIResponse(
        bot_id=bot_id,
        session_id=session_id,
        total_trades=total_trades,
        win_rate=win_rate,
        realized_pnl=realized_pnl,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=drawdown
    )

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

@app.post("/api/bots/{bot_id}/sessions/start", response_model=schemas.BotSessionResponse)
def start_lap_session(bot_id: str, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    active_lap = db.query(models.BotSession).filter(
        models.BotSession.bot_id == bot_id,
        models.BotSession.session_type == "lap",
        models.BotSession.status == "active"
    ).first()

    if active_lap:
        raise HTTPException(status_code=400, detail="A lap session is already active for this bot.")

    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    starting_equity = portfolio.initial_capital if portfolio else 0.0

    session = models.BotSession(
        bot_id=bot_id,
        session_type="lap",
        starting_equity=starting_equity,
        max_equity=starting_equity,
        min_equity=starting_equity
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    
    return session

@app.post("/api/bots/{bot_id}/sessions/stop", response_model=schemas.BotSessionResponse)
def stop_lap_session(bot_id: str, db: Session = Depends(get_db)):
    session = db.query(models.BotSession).filter(
        models.BotSession.bot_id == bot_id,
        models.BotSession.session_type == "lap",
        models.BotSession.status == "active"
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="No active lap session found to stop.")

    session.status = "completed"
    session.end_time = func.now()
    db.commit()
    db.refresh(session)
    
    return session

@app.get("/api/bots/{bot_id}/sessions", response_model=List[schemas.BotSessionResponse])
def get_bot_sessions(bot_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    sessions = db.query(models.BotSession).filter(models.BotSession.bot_id == bot_id).order_by(models.BotSession.start_time.desc()).offset(skip).limit(limit).all()
    return sessions
