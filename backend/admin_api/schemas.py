from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class BotStrategyCreate(BaseModel):
    name: str
    strategy_type: str  # "alpha", "market_maker", "custom"
    config: Optional[Dict[str, Any]] = {}

class BotStrategyResponse(BaseModel):
    id: str
    name: str
    strategy_type: str
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class BotCreate(BaseModel):
    name: str
    strategy_type: Optional[str] = None
    strategy_config: Optional[Dict[str, Any]] = {}

class BotResponse(BaseModel):
    id: str
    name: str
    api_key: str
    strategy_id: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class BotWithStrategyResponse(BaseModel):
    id: str
    name: str
    api_key: str
    status: str
    strategy: Optional[BotStrategyResponse] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class BotKPIResponse(BaseModel):
    id: str
    bot_id: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    strategy_metrics: Dict[str, Any]
    updated_at: datetime

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

