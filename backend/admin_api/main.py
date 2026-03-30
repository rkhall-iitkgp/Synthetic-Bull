import uuid
import secrets
import asyncio
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

import models, schemas
from database import engine, get_db
from worker import logger_worker

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
        
    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    positions = db.query(models.Position).filter(models.Position.bot_id == bot_id).all()
    
    return {
        "cash_balance": portfolio.cash_balance if portfolio else 0.0,
        "positions": [schemas.PositionResponse.model_validate(p) for p in positions]
    }
