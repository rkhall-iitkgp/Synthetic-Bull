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
