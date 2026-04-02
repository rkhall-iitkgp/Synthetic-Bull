import os

# Exchange connection
EXCHANGE_WS_URL = os.getenv("EXCHANGE_WS_URL", "ws://127.0.0.1:9001")
BOT_API_KEY = os.getenv("BOT_API_KEY", os.getenv("ALPHA_BOT_API_KEY", ""))

# Bot instance settings (generic BOT_* vars help when running cloned copies)
ALPHA_BOT_PORT = int(os.getenv("BOT_STATUS_PORT", os.getenv("ALPHA_BOT_PORT", "3001")))
ALPHA_SYMBOL = os.getenv("BOT_SYMBOL", os.getenv("ALPHA_SYMBOL", "AAPL"))

# Capital
STARTING_EQUITY = float(os.getenv("STARTING_EQUITY", "100000.0"))
PNL_FLOOR = float(os.getenv("PNL_FLOOR", "80000.0"))

# Alpha bot parameters
ALPHA_RISK_PCT = float(os.getenv("ALPHA_RISK_PCT", "0.015"))
ALPHA_STOP_PCT = float(os.getenv("ALPHA_STOP_PCT", "0.012"))
ALPHA_TP_PCT = float(os.getenv("ALPHA_TP_PCT", "0.020"))
ALPHA_DAILY_DRAWDOWN = float(os.getenv("ALPHA_DAILY_DRAWDOWN", "0.05"))
ALPHA_COOLDOWN_TICKS = int(os.getenv("ALPHA_COOLDOWN_TICKS", "15"))
ALPHA_MIN_TICKS = int(os.getenv("ALPHA_MIN_TICKS", "100"))
ALPHA_PRICE_WINDOW = int(os.getenv("ALPHA_PRICE_WINDOW", "200"))
ALPHA_MAX_POSITION_PCT = float(os.getenv("ALPHA_MAX_POSITION_PCT", "0.20"))

# Adaptive alpha bot parameters
ALPHA_HURST_WINDOW = int(os.getenv("ALPHA_HURST_WINDOW", "100"))
ALPHA_HURST_TRENDING = float(os.getenv("ALPHA_HURST_TRENDING", "0.6"))
ALPHA_HURST_MR = float(os.getenv("ALPHA_HURST_MR", "0.4"))
ALPHA_ATR_PERIOD = int(os.getenv("ALPHA_ATR_PERIOD", "14"))
ALPHA_ATR_RISK_MULT = float(os.getenv("ALPHA_ATR_RISK_MULT", "10.0"))
ALPHA_MOMENTUM_THRESH = float(os.getenv("ALPHA_MOMENTUM_THRESH", "0.5"))
ALPHA_ZSCORE_THRESH = float(os.getenv("ALPHA_ZSCORE_THRESH", "1.5"))
