from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class BotCreate(BaseModel):
    name: str
    strategy_module: Optional[str] = None

class BotResponse(BaseModel):
    id: str
    name: str
    api_key: str
    status: str
    strategy_module: Optional[str] = None
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
    run_id: Optional[str] = None
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
    run_id: Optional[str] = None
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
    run_id: Optional[str] = None
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
    run_id: Optional[str] = None
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


class MarketDatasetCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_type: str = "generated"
    symbols_json: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    event_count: int = 0
    schema_version: str = "v1"
    file_path: Optional[str] = None
    checksum: Optional[str] = None
    format_type: str = "ndjson_v1"
    status: str = "ready"


class MarketDatasetResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    source_type: str
    symbols_json: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    event_count: int
    schema_version: str
    file_path: Optional[str] = None
    checksum: Optional[str] = None
    format_type: str
    validation_error: Optional[str] = None
    last_validated_at: Optional[datetime] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessionTemplateCreate(BaseModel):
    name: str
    mode: str = "live"
    is_enabled: str = "true"
    timezone: str = "UTC"
    recurrence_rule: Optional[str] = None
    schedule_start_time: Optional[datetime] = None
    schedule_end_time: Optional[datetime] = None
    symbols_json: Optional[str] = None
    launch_config_json: Optional[str] = None
    risk_profile: Optional[str] = None
    replay_dataset_id: Optional[str] = None
    replay_speed: float = 1.0


class SessionTemplateUpdate(BaseModel):
    name: Optional[str] = None
    mode: Optional[str] = None
    is_enabled: Optional[str] = None
    timezone: Optional[str] = None
    recurrence_rule: Optional[str] = None
    schedule_start_time: Optional[datetime] = None
    schedule_end_time: Optional[datetime] = None
    symbols_json: Optional[str] = None
    launch_config_json: Optional[str] = None
    risk_profile: Optional[str] = None
    replay_dataset_id: Optional[str] = None
    replay_speed: Optional[float] = None


class SessionTemplateResponse(BaseModel):
    id: str
    name: str
    mode: str
    is_enabled: str
    timezone: str
    recurrence_rule: Optional[str] = None
    schedule_start_time: Optional[datetime] = None
    schedule_end_time: Optional[datetime] = None
    symbols_json: Optional[str] = None
    launch_config_json: Optional[str] = None
    risk_profile: Optional[str] = None
    replay_dataset_id: Optional[str] = None
    replay_speed: float
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessionRunCreateFromTemplate(BaseModel):
    template_id: str
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    bot_ids: Optional[List[str]] = None


class SessionRunResponse(BaseModel):
    id: str
    template_id: Optional[str] = None
    mode: str
    status: str
    timezone: str
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    actual_start_time: Optional[datetime] = None
    actual_end_time: Optional[datetime] = None
    replay_dataset_id: Optional[str] = None
    replay_speed: float
    replay_endpoint: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessionRunEventResponse(BaseModel):
    id: str
    run_id: str
    event_type: str
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    message: Optional[str] = None
    payload_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SessionRunBotResponse(BaseModel):
    id: str
    run_id: str
    bot_id: str
    status: str
    strategy_module: Optional[str] = None
    pid: Optional[int] = None
    launch_meta_json: Optional[str] = None
    started_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DatasetValidationResponse(BaseModel):
    ok: bool
    event_count: int
    symbols: List[str]
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None


class ReplayControlResponse(BaseModel):
    run_id: str
    ready: bool
    clients: int
    events_total: int
    events_sent: int
    status: str


class ReplayCandleInput(BaseModel):
    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class ReplayRunFromCandlesRequest(BaseModel):
    symbol: str
    timeframe_seconds: int = 1
    replay_speed: float = 1.0
    start_index: int
    end_index: int
    bot_ids: List[str]
    candles: List[ReplayCandleInput]
    name: Optional[str] = None
    timezone: str = "UTC"


class ReplayRunFromCandlesResponse(BaseModel):
    run_id: str
    dataset_id: str
    template_id: str
    status: str
    replay_endpoint: Optional[str] = None
    candles_used: int
