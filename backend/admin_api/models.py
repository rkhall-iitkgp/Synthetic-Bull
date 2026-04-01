import uuid
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

def generate_uuid():
    return str(uuid.uuid4())

class BotStrategy(Base):
    __tablename__ = "bot_strategies"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    name = Column(String, index=True)
    strategy_type = Column(String, index=True)  # "alpha", "market_maker", "custom"
    config = Column(JSON, default={})  # Store strategy-specific configuration
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    bots = relationship("Bot", back_populates="strategy", cascade="all, delete-orphan")
    kpis = relationship("BotKPI", back_populates="strategy", cascade="all, delete-orphan")

class Bot(Base):
    __tablename__ = "bots"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    name = Column(String, index=True)
    api_key = Column(String, unique=True, index=True)
    strategy_id = Column(String, ForeignKey("bot_strategies.id"), nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    strategy = relationship("BotStrategy", back_populates="bots")
    portfolios = relationship("Portfolio", back_populates="bot", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="bot", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="bot", cascade="all, delete-orphan")
    kpis = relationship("BotKPI", back_populates="bot", cascade="all, delete-orphan")

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

    bot = relationship("Bot", back_populates="positions")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    symbol = Column(String, index=True)
    side = Column(String)  # buy/sell
    price = Column(Float)
    qty = Column(Float)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    bot = relationship("Bot", back_populates="trades")

class BotKPI(Base):
    __tablename__ = "bot_kpis"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    bot_id = Column(String, ForeignKey("bots.id"))
    strategy_id = Column(String, ForeignKey("bot_strategies.id"), nullable=True)
    
    # Common KPIs
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    
    # Strategy-specific metrics (stored as JSON for flexibility)
    strategy_metrics = Column(JSON, default={})
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    bot = relationship("Bot", back_populates="kpis")
    strategy = relationship("BotStrategy", back_populates="kpis")

