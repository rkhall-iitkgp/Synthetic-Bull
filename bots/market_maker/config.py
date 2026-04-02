import os

# Exchange connection
EXCHANGE_WS_URL = os.getenv("EXCHANGE_WS_URL", "ws://127.0.0.1:9001")
BOT_API_KEY = os.getenv("BOT_API_KEY", os.getenv("MM_BOT_API_KEY", ""))

# Bot instance settings (generic BOT_* vars help when running cloned copies)
MM_BOT_PORT = int(os.getenv("BOT_STATUS_PORT", os.getenv("MM_BOT_PORT", "3002")))
MM_SYMBOL = os.getenv("BOT_SYMBOL", os.getenv("MM_SYMBOL", "AAPL"))

# Capital
STARTING_EQUITY = float(os.getenv("STARTING_EQUITY", "100000.0"))
PNL_FLOOR = float(os.getenv("PNL_FLOOR", "80000.0"))

# Market maker parameters
MM_BASE_SPREAD_PCT = float(os.getenv("MM_BASE_SPREAD_PCT", "0.0018"))
MM_QUOTE_QTY = float(os.getenv("MM_QUOTE_QTY", "0.05"))
MM_MAX_INVENTORY = float(os.getenv("MM_MAX_INVENTORY", "0.5"))
MM_INVENTORY_SKEW = float(os.getenv("MM_INVENTORY_SKEW", "0.5"))
MM_REQUOTE_INTERVAL = float(os.getenv("MM_REQUOTE_INTERVAL", "0.5"))
MM_MAX_ORDERS = int(os.getenv("MM_MAX_ORDERS", "10"))
