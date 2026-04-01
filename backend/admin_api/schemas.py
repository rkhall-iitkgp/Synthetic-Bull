from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class BotCreate(BaseModel):
    name: str

class BotResponse(BaseModel):
    id: str
    name: str
    api_key: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class PortfolioResponse(BaseModel):
    bot_id: str
    cash_balance: float
    updated_at: datetime

    class Config:
        from_attributes = True

class PositionResponse(BaseModel):
    symbol: str
    qty: float
    avg_entry_price: float
    unrealized_pnl: float = 0.0

    class Config:
        from_attributes = True

class TradeResponse(BaseModel):
    id: str
    session_id: Optional[str] = None
    symbol: str
    side: str
    price: float
    qty: float
    timestamp: datetime

    class Config:
        from_attributes = True

class BotSessionResponse(BaseModel):
    id: str
    bot_id: str
    session_type: str
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    starting_equity: float
    max_equity: float
    min_equity: float
    realized_pnl: float

    class Config:
        from_attributes = True

class TradeRoundResponse(BaseModel):
    id: str
    bot_id: str
    session_id: Optional[str] = None
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    pct_return: float
    closed_at: datetime

    class Config:
        from_attributes = True

class BotKPIResponse(BaseModel):
    bot_id: str
    session_id: Optional[str] = None
    total_trades: int
    win_rate: float
    realized_pnl: float
    sharpe_ratio: float
    max_drawdown: float

class DepositRequest(BaseModel):
    amount: float

class DepositResponse(BaseModel):
    bot_id: str
    amount: float
    new_cash_balance: float
