import os

# Exchange connection
EXCHANGE_WS_URL = os.getenv("EXCHANGE_WS_URL", "ws://127.0.0.1:9001")
# Docker: set EXCHANGE_WS_URL=ws://engine:9001

# Bot HTTP status servers
ALPHA_BOT_PORT = int(os.getenv("ALPHA_BOT_PORT", "3001"))
MM_BOT_PORT = int(os.getenv("MM_BOT_PORT", "3002"))

# Capital
STARTING_EQUITY = float(os.getenv("STARTING_EQUITY", "100000.0"))

# Global PnL floor — halt all trading if portfolio drops below this
PNL_FLOOR = float(os.getenv("PNL_FLOOR", "80000.0"))

# Alpha bot parameters
ALPHA_RISK_PCT = float(os.getenv("ALPHA_RISK_PCT", "0.015"))
ALPHA_STOP_PCT = float(os.getenv("ALPHA_STOP_PCT", "0.012"))
ALPHA_TP_PCT = float(os.getenv("ALPHA_TP_PCT", "0.020"))
ALPHA_SCORE_THRESHOLD = float(os.getenv("ALPHA_SCORE_THRESHOLD", "0.40"))
ALPHA_DAILY_DRAWDOWN = float(os.getenv("ALPHA_DAILY_DRAWDOWN", "0.05"))
ALPHA_COOLDOWN_TICKS = int(os.getenv("ALPHA_COOLDOWN_TICKS", "15"))
ALPHA_MIN_TICKS = int(os.getenv("ALPHA_MIN_TICKS", "100"))
ALPHA_PRICE_WINDOW = int(os.getenv("ALPHA_PRICE_WINDOW", "200"))
ALPHA_MAX_POSITION_PCT = float(os.getenv("ALPHA_MAX_POSITION_PCT", "0.20"))

# Alpha bot indicator periods
EMA_SHORT = 12
EMA_LONG = 26
RSI_PERIOD = 50
MACD_SIGNAL = 9
BB_PERIOD = 20

# Market maker parameters
MM_BASE_SPREAD_PCT = float(os.getenv("MM_BASE_SPREAD_PCT", "0.0018"))
MM_QUOTE_QTY = float(os.getenv("MM_QUOTE_QTY", "0.05"))
MM_MAX_INVENTORY = float(os.getenv("MM_MAX_INVENTORY", "0.5"))
MM_INVENTORY_SKEW = float(os.getenv("MM_INVENTORY_SKEW", "0.5"))
MM_REQUOTE_INTERVAL = float(os.getenv("MM_REQUOTE_INTERVAL", "0.5"))
MM_MAX_ORDERS = int(os.getenv("MM_MAX_ORDERS", "10"))

# Symbol selection
ALPHA_SYMBOL = os.getenv("ALPHA_SYMBOL", "BTC")
MM_SYMBOL = os.getenv("MM_SYMBOL", "AAPL")

# Minimum order quantity per symbol
ALPHA_MIN_QTY = float(os.getenv("ALPHA_MIN_QTY", "0.001"))
MM_MIN_QTY = float(os.getenv("MM_MIN_QTY", "0.001"))
