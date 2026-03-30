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

    class Config:
        from_attributes = True

class TradeResponse(BaseModel):
    id: str
    symbol: str
    side: str
    price: float
    qty: float
    timestamp: datetime

    class Config:
        from_attributes = True

class DepositRequest(BaseModel):
    amount: float

class DepositResponse(BaseModel):
    bot_id: str
    amount: float
    new_cash_balance: float
