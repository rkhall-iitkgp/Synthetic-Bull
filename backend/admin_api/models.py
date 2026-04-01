import uuid
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    portfolios = relationship("Portfolio", back_populates="bot", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="bot", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="bot", cascade="all, delete-orphan")
    sessions = relationship("BotSession", back_populates="bot", cascade="all, delete-orphan")
    trade_rounds = relationship("TradeRound", back_populates="bot", cascade="all, delete-orphan")

class BotSession(Base):
    __tablename__ = "bot_sessions"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    session_type = Column(String)  # connection or lap
    status = Column(String, default="active")  # active or completed
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    starting_equity = Column(Float, default=0.0)
    max_equity = Column(Float, default=0.0)
    min_equity = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)

    bot = relationship("Bot", back_populates="sessions")
    trades = relationship("Trade", back_populates="session")
    trade_rounds = relationship("TradeRound", back_populates="session")

class TradeRound(Base):
    __tablename__ = "trade_rounds"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    session_id = Column(String, ForeignKey("bot_sessions.id"), nullable=True)
    symbol = Column(String, index=True)
    side = Column(String)
    entry_price = Column(Float)
    exit_price = Column(Float)
    qty = Column(Float)
    pnl = Column(Float)
    pct_return = Column(Float)
    closed_at = Column(DateTime(timezone=True), server_default=func.now())

    bot = relationship("Bot", back_populates="trade_rounds")
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
    symbol = Column(String, index=True)
    side = Column(String)  # buy/sell
    price = Column(Float)
    qty = Column(Float)
    unclosed_qty = Column(Float)  # Added for FIFO matching
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    bot = relationship("Bot", back_populates="trades")
    session = relationship("BotSession", back_populates="trades")
