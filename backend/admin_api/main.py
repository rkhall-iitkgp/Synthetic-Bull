import uuid
import secrets
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
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


def _normalize_bot_identifier(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


def _base_bot_identifier(value: str) -> str:
    normalized = _normalize_bot_identifier(value)
    if normalized.endswith(" bot"):
        normalized = normalized[:-4]
    if normalized.endswith("bot"):
        normalized = normalized[:-3]
    return " ".join(normalized.split()).strip()


def resolve_bot(db: Session, bot_identifier: str) -> models.Bot | None:
    # 1) Direct id match (UUID path)
    bot = db.query(models.Bot).filter(models.Bot.id == bot_identifier).first()
    if bot:
        return bot

    # 2) Exact name match (case-insensitive)
    bot = db.query(models.Bot).filter(func.lower(models.Bot.name) == bot_identifier.strip().lower()).first()
    if bot:
        return bot

    # 3) Slug-style match: alpha_bot / alpha-bot / Alpha Bot -> compare normalized forms
    normalized = _normalize_bot_identifier(bot_identifier)
    candidates = db.query(models.Bot).all()
    for candidate in candidates:
        if _normalize_bot_identifier(candidate.name) == normalized:
            return candidate

    # 4) Fuzzy alias match, e.g. "alpha_bot" -> "Alpha-01"
    base = _base_bot_identifier(bot_identifier)
    if base:
        fuzzy_matches: list[models.Bot] = []
        for candidate in candidates:
            cand_base = _base_bot_identifier(candidate.name)
            if not cand_base:
                continue
            if cand_base.startswith(base) or base.startswith(cand_base):
                fuzzy_matches.append(candidate)
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]
    return None


def _to_epoch_ms(ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int(ts.timestamp() * 1000)


def _apply_trade_to_position(pos: dict, side: str, price: float, qty: float) -> float:
    """Apply one trade to a symbol position and return realized PnL delta.

    Position dict shape: {"holdings": float, "avg_cost": float}
    Mirrors the matching engine's long/short accounting semantics.
    """
    holdings = float(pos.get("holdings", 0.0))
    avg_cost = float(pos.get("avg_cost", 0.0))
    realized_delta = 0.0

    if side == "buy":
        if holdings >= 0.0:
            # Add to long
            total_cost = (avg_cost * holdings) + (price * qty)
            holdings += qty
            avg_cost = (total_cost / holdings) if holdings > 1e-12 else 0.0
        else:
            # Cover short first
            cover_qty = min(qty, -holdings)
            realized_delta += cover_qty * (avg_cost - price)
            holdings += qty
            if holdings > 1e-12:
                avg_cost = price
            elif abs(holdings) < 1e-12:
                holdings = 0.0
                avg_cost = 0.0
    else:
        if holdings > 0.0:
            # Close long first
            sell_qty = min(qty, holdings)
            realized_delta += sell_qty * (price - avg_cost)
            holdings -= qty
            if holdings < -1e-12:
                avg_cost = price
            elif abs(holdings) < 1e-12:
                holdings = 0.0
                avg_cost = 0.0
        else:
            # Add to short
            total_proceeds = (avg_cost * (-holdings)) + (price * qty)
            holdings -= qty
            avg_cost = (total_proceeds / (-holdings)) if abs(holdings) > 1e-12 else 0.0

    pos["holdings"] = holdings
    pos["avg_cost"] = avg_cost
    return realized_delta

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.post("/api/strategies", response_model=schemas.BotStrategyResponse)
def create_strategy(strategy: schemas.BotStrategyCreate, db: Session = Depends(get_db)):
    """Create a new bot strategy template"""
    db_strategy = models.BotStrategy(
        name=strategy.name,
        strategy_type=strategy.strategy_type,
        config=strategy.config or {}
    )
    db.add(db_strategy)
    db.commit()
    db.refresh(db_strategy)
    return db_strategy

@app.get("/api/strategies", response_model=List[schemas.BotStrategyResponse])
def get_strategies(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get all available bot strategies"""
    strategies = db.query(models.BotStrategy).offset(skip).limit(limit).all()
    return strategies

@app.get("/api/strategies/{strategy_id}", response_model=schemas.BotStrategyResponse)
def get_strategy(strategy_id: str, db: Session = Depends(get_db)):
    """Get a specific bot strategy"""
    strategy = db.query(models.BotStrategy).filter(models.BotStrategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy

@app.post("/api/bots", response_model=schemas.BotResponse)
def create_bot(bot: schemas.BotCreate, db: Session = Depends(get_db)):
    api_key = generate_api_key()
    
    # If strategy_type is provided, create a strategy for this bot
    strategy_id = None
    if bot.strategy_type:
        db_strategy = models.BotStrategy(
            name=f"{bot.name}_strategy",
            strategy_type=bot.strategy_type,
            config=bot.strategy_config or {}
        )
        db.add(db_strategy)
        db.commit()
        db.refresh(db_strategy)
        strategy_id = db_strategy.id
    
    db_bot = models.Bot(
        name=bot.name, 
        api_key=api_key,
        strategy_id=strategy_id
    )
    db.add(db_bot)
    db.commit()
    db.refresh(db_bot)
    
    # Initialize portfolio
    db_portfolio = models.Portfolio(bot_id=db_bot.id, cash_balance=100000.0)
    db.add(db_portfolio)
    
    # Initialize KPI tracking
    db_kpi = models.BotKPI(bot_id=db_bot.id, strategy_id=strategy_id)
    db.add(db_kpi)
    db.commit()
    
    return db_bot

@app.get("/api/bots", response_model=List[schemas.BotResponse])
def get_bots(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    bots = db.query(models.Bot).offset(skip).limit(limit).all()
    return bots

@app.get("/api/bots/{bot_id}/trades", response_model=List[schemas.TradeResponse])
def get_bot_trades(bot_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    bot = resolve_bot(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    trades = (
        db.query(models.Trade)
        .filter(models.Trade.bot_id == bot.id)
        .order_by(models.Trade.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return trades

@app.get("/api/bots/{bot_id}/portfolio")
def get_bot_portfolio(bot_id: str, db: Session = Depends(get_db)):
    bot = resolve_bot(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Compute portfolio dynamically from trades
    trades = db.query(models.Trade).filter(models.Trade.bot_id == bot.id).all()

    portfolio_record = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot.id).first()
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

    bot = resolve_bot(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot.id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Update initial_capital (the base for dynamic cash computation)
    portfolio.initial_capital = (portfolio.initial_capital or 100000.0) + req.amount
    db.commit()
    db.refresh(portfolio)

    # Notify the C++ engine to update in-memory portfolio
    await deposit_queue.put({"bot_id": bot.id, "amount": req.amount})

    # Recompute current cash for response
    trades = db.query(models.Trade).filter(models.Trade.bot_id == bot.id).all()
    cash = portfolio.initial_capital
    for t in trades:
        value = t.price * t.qty
        if t.side in ("buy", "BUY"):
            cash -= value
        else:
            cash += value

    return schemas.DepositResponse(
        bot_id=bot.id,
        amount=req.amount,
        new_cash_balance=round(cash, 2)
    )


@app.get("/api/bots/{bot_id}/pnl")
def get_bot_pnl(bot_id: str, period: str = "7d", db: Session = Depends(get_db)):
    period_map = {
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    if period not in period_map:
        raise HTTPException(status_code=400, detail="Invalid period. Use one of: 1d, 7d, 30d")

    bot = resolve_bot(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    portfolio_record = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot.id).first()
    initial_capital = (
        portfolio_record.initial_capital
        if portfolio_record and portfolio_record.initial_capital is not None
        else 100000.0
    )

    trades = (
        db.query(models.Trade)
        .filter(models.Trade.bot_id == bot.id)
        .order_by(models.Trade.timestamp.asc())
        .all()
    )

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - period_map[period]

    cash_balance = float(initial_capital)
    positions: dict[str, dict] = {}
    realized_pnl = 0.0

    history: list[dict] = []
    for t in trades:
        side = (t.side or "").lower()
        qty = float(t.qty)
        price = float(t.price)
        symbol = t.symbol
        notional = price * qty

        if side == "buy":
            cash_balance -= notional
        else:
            cash_balance += notional

        if symbol not in positions:
            positions[symbol] = {"holdings": 0.0, "avg_cost": 0.0}
        realized_pnl += _apply_trade_to_position(positions[symbol], side, price, qty)

        trade_ts = t.timestamp
        if trade_ts.tzinfo is None:
            trade_ts = trade_ts.replace(tzinfo=timezone.utc)

        if trade_ts >= cutoff:
            pnl = realized_pnl
            equity = float(initial_capital) + pnl
            history.append(
                {
                    "timestamp": _to_epoch_ms(trade_ts),
                    "pnl": round(pnl, 2),
                    "equity": round(equity, 2),
                }
            )

    current_pnl = realized_pnl
    total_equity = float(initial_capital) + current_pnl

    # Always provide at least one point for charting in no-trade windows.
    if not history:
        history = [
            {
                "timestamp": _to_epoch_ms(now_utc),
                "pnl": round(current_pnl, 2),
                "equity": round(total_equity, 2),
            }
        ]

    return {
        "bot_id": bot.id,
        "current_pnl": round(current_pnl, 2),
        "total_equity": round(total_equity, 2),
        "history": history,
    }

@app.get("/api/bots/{bot_id}/kpi", response_model=schemas.BotKPIResponse)
def get_bot_kpi(bot_id: str, db: Session = Depends(get_db)):
    """Get KPI data for a specific bot"""
    bot = resolve_bot(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    kpi = db.query(models.BotKPI).filter(models.BotKPI.bot_id == bot.id).first()
    if not kpi:
        # Create a default KPI record if it doesn't exist
        kpi = models.BotKPI(bot_id=bot.id, strategy_id=bot.strategy_id)
        db.add(kpi)
        db.commit()
        db.refresh(kpi)
    
    return kpi

@app.post("/api/bots/{bot_id}/kpi/update")
def update_bot_kpi(bot_id: str, kpi_data: dict, db: Session = Depends(get_db)):
    """Update KPI data for a specific bot"""
    bot = resolve_bot(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    kpi = db.query(models.BotKPI).filter(models.BotKPI.bot_id == bot.id).first()
    if not kpi:
        kpi = models.BotKPI(bot_id=bot.id, strategy_id=bot.strategy_id)
        db.add(kpi)
        db.commit()
        db.refresh(kpi)
    
    # Update KPI fields from the provided data
    for field, value in kpi_data.items():
        if hasattr(kpi, field):
            setattr(kpi, field, value)
    
    db.commit()
    db.refresh(kpi)
    return {"status": "updated", "kpi_id": kpi.id}

@app.get("/api/bots/{bot_id}", response_model=schemas.BotWithStrategyResponse)
def get_bot_details(bot_id: str, db: Session = Depends(get_db)):
    """Get detailed bot information including strategy"""
    bot = resolve_bot(db, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    return bot
