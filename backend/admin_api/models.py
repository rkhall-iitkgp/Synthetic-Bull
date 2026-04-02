import uuid
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Bot(Base):
    __tablename__ = "bots"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    name = Column(String, index=True)
    api_key = Column(String, unique=True, index=True)
    status = Column(String, default="active")
    strategy_module = Column(String, default="alpha.main")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    portfolios = relationship("Portfolio", back_populates="bot", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="bot", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="bot", cascade="all, delete-orphan")
    sessions = relationship("BotSession", back_populates="bot", cascade="all, delete-orphan")
    trade_rounds = relationship("TradeRound", back_populates="bot", cascade="all, delete-orphan")
    session_run_assignments = relationship("SessionRunBot", back_populates="bot", cascade="all, delete-orphan")


class MarketDataset(Base):
    __tablename__ = "market_datasets"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    name = Column(String, index=True)
    description = Column(Text, nullable=True)
    source_type = Column(String, default="generated")
    symbols_json = Column(Text, nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    event_count = Column(Integer, default=0)
    schema_version = Column(String, default="v1")
    file_path = Column(String, nullable=True)
    checksum = Column(String, nullable=True)
    format_type = Column(String, default="ndjson_v1")
    validation_error = Column(Text, nullable=True)
    last_validated_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default="ready")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    templates = relationship("SessionTemplate", back_populates="replay_dataset")
    runs = relationship("SessionRun", back_populates="replay_dataset")


class SessionTemplate(Base):
    __tablename__ = "session_templates"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    name = Column(String, index=True)
    mode = Column(String, default="live")  # live or replay
    is_enabled = Column(String, default="true")
    timezone = Column(String, default="UTC")
    recurrence_rule = Column(String, nullable=True)
    schedule_start_time = Column(DateTime(timezone=True), nullable=True)
    schedule_end_time = Column(DateTime(timezone=True), nullable=True)
    symbols_json = Column(Text, nullable=True)
    launch_config_json = Column(Text, nullable=True)
    risk_profile = Column(String, nullable=True)
    replay_dataset_id = Column(String, ForeignKey("market_datasets.id"), nullable=True)
    replay_speed = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    replay_dataset = relationship("MarketDataset", back_populates="templates")
    runs = relationship("SessionRun", back_populates="template", cascade="all, delete-orphan")


class SessionRun(Base):
    __tablename__ = "session_runs"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    template_id = Column(String, ForeignKey("session_templates.id"), nullable=True)
    mode = Column(String, default="live")  # live or replay
    status = Column(String, default="scheduled")
    timezone = Column(String, default="UTC")
    scheduled_start_time = Column(DateTime(timezone=True), nullable=True)
    scheduled_end_time = Column(DateTime(timezone=True), nullable=True)
    actual_start_time = Column(DateTime(timezone=True), nullable=True)
    actual_end_time = Column(DateTime(timezone=True), nullable=True)
    replay_dataset_id = Column(String, ForeignKey("market_datasets.id"), nullable=True)
    replay_speed = Column(Float, default=1.0)
    replay_endpoint = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    template = relationship("SessionTemplate", back_populates="runs")
    replay_dataset = relationship("MarketDataset", back_populates="runs")
    assignments = relationship("SessionRunBot", back_populates="run", cascade="all, delete-orphan")
    events = relationship("SessionRunEvent", back_populates="run", cascade="all, delete-orphan")


class SessionRunBot(Base):
    __tablename__ = "session_run_bots"
    __table_args__ = (UniqueConstraint("run_id", "bot_id", name="uq_session_run_bot"),)

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    run_id = Column(String, ForeignKey("session_runs.id"), index=True)
    bot_id = Column(String, ForeignKey("bots.id"), index=True)
    status = Column(String, default="pending")
    strategy_module = Column(String, nullable=True)
    pid = Column(Integer, nullable=True)
    launch_meta_json = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    run = relationship("SessionRun", back_populates="assignments")
    bot = relationship("Bot", back_populates="session_run_assignments")


class SessionRunEvent(Base):
    __tablename__ = "session_run_events"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    run_id = Column(String, ForeignKey("session_runs.id"), index=True)
    event_type = Column(String, default="info")
    from_state = Column(String, nullable=True)
    to_state = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("SessionRun", back_populates="events")

class BotSession(Base):
    __tablename__ = "bot_sessions"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    run_id = Column(String, ForeignKey("session_runs.id"), nullable=True)
    session_type = Column(String)  # connection or lap
    status = Column(String, default="active")  # active or completed
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    starting_equity = Column(Float, default=0.0)
    max_equity = Column(Float, default=0.0)
    min_equity = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)

    bot = relationship("Bot", back_populates="sessions")
    run = relationship("SessionRun")
    trades = relationship("Trade", back_populates="session")
    trade_rounds = relationship("TradeRound", back_populates="session")

class TradeRound(Base):
    __tablename__ = "trade_rounds"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    session_id = Column(String, ForeignKey("bot_sessions.id"), nullable=True)
    run_id = Column(String, ForeignKey("session_runs.id"), nullable=True)
    symbol = Column(String, index=True)
    side = Column(String)
    entry_price = Column(Float)
    exit_price = Column(Float)
    qty = Column(Float)
    pnl = Column(Float)
    pct_return = Column(Float)
    closed_at = Column(DateTime(timezone=True), server_default=func.now())

    bot = relationship("Bot", back_populates="trade_rounds")
    run = relationship("SessionRun")
    session = relationship("BotSession", back_populates="trade_rounds")

class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    cash_balance = Column(Float, default=100000.0)
    initial_capital = Column(Float, default=100000.0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    bot = relationship("Bot", back_populates="portfolios")

class Position(Base):
    __tablename__ = "positions"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    symbol = Column(String, index=True)
    qty = Column(Float, default=0.0)
    avg_entry_price = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)

    bot = relationship("Bot", back_populates="positions")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    session_id = Column(String, ForeignKey("bot_sessions.id"), nullable=True)
    run_id = Column(String, ForeignKey("session_runs.id"), nullable=True)
    symbol = Column(String, index=True)
    side = Column(String)  # buy/sell
    price = Column(Float)
    qty = Column(Float)
    unclosed_qty = Column(Float)  # Added for FIFO matching
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    bot = relationship("Bot", back_populates="trades")
    run = relationship("SessionRun")
    session = relationship("BotSession", back_populates="trades")
