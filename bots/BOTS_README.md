# BOTS — Complete Implementation Guide

## Project Synthetic-Bull | IIT Kharagpur × NextBull OpenSoft 2026

> This document is the single source of truth for GitHub Copilot to implement
> the entire `bots/` directory. Read every section completely before generating
> any file. Every design decision, data type, formula, and edge case is
> specified here. Do not invent behaviour that is not described.

---

## 0. Context & Constraint

### What already exists (do not touch)

- `backend/` — C++ uWebSockets server on port 9001. Already complete.
- `frontend/` — React + TypeScript frontend on port 3000. Already complete.

### What you are building

The `bots/` directory containing two autonomous trading bots written in
**Python 3.12** using **asyncio** throughout. No threads. No blocking calls.

- **Alpha Bot** — trend-following quant bot using four technical indicators.
  Runs its own status HTTP server on port 3001.
- **Market Maker Bot** — liquidity provider that continuously quotes both
  sides of the book. Runs its own status HTTP server on port 3002.

Both bots:

- Connect to `ws://localhost:9001` (or `ws://backend:9001` inside Docker)
- Speak the exact JSON protocol documented in section 3
- Start with $100,000 simulated capital (tracked server-side)
- Run as independent asyncio processes — one process per bot
- Are Docker-safe: all hostnames/ports read from environment variables

### Language & libraries

```
Python        3.12
websockets    15.x     — asyncio WebSocket client
fastapi       0.115.x  — status HTTP server
uvicorn       0.34.x   — ASGI runner
numpy         2.x      — indicator math
aiohttp       3.12.x   — (imported but not required if websockets covers all needs)
```

No other third-party libraries. No SQLite. No Redis. No databases.
All state lives in memory for the duration of the process.

---

## 1. Directory Structure

Generate exactly these files and no others:

```
bots/
├── requirements.txt
├── shared/
│   ├── __init__.py              (empty)
│   ├── config.py                (all env-var configuration)
│   └── exchange_client.py       (WebSocket connection to backend)
├── alpha/
│   ├── __init__.py              (empty)
│   ├── main.py                  (entry point — asyncio.run)
│   ├── tick_buffer.py           (rolling price window)
│   ├── indicators.py            (EMA, RSI, MACD, Bollinger Bands)
│   ├── signal_scorer.py         (weighted vote → BUY/SELL/HOLD)
│   ├── risk_manager.py          (position sizing, stop/TP tracking)
│   ├── drawdown_guard.py        (daily 5% circuit breaker)
│   ├── kpi_tracker.py           (Sharpe, win rate, max drawdown)
│   └── status_server.py         (FastAPI on port 3001)
└── market_maker/
    ├── __init__.py              (empty)
    ├── main.py                  (entry point — asyncio.run)
    ├── inventory_manager.py     (position tracking + skew)
    ├── spread_calculator.py     (bid/ask price computation)
    ├── order_tracker.py         (active order ID management)
    ├── kpi_tracker.py           (PnL, fill rate, spread captured)
    └── status_server.py         (FastAPI on port 3002)
```

---

## 2. Exchange WebSocket Protocol

The backend speaks JSON over WebSocket. Study every message type.
The bots must handle all of them correctly.

### 2.1 Connection handshake

Immediately on connect, the server sends three messages in sequence:

user_id format: "user_1", "user_2", etc. — assigned sequentially
by the server. Store as str. Used to detect own fills in trade messages.

```json
{ "type": "welcome", "user_id": "user_1", "price": 50234.17 }
```

```json
{
  "type": "orderbook",
  "mid": 50234.17,
  "spread": 3.8,
  "ts": 1712000000000000,
  "bids": [
    [50232.0, 0.42, 3],
    [50230.0, 1.1, 5]
  ],
  "asks": [
    [50235.8, 0.35, 2],
    [50237.5, 0.88, 4]
  ]
}
```

```json
{
  "type": "portfolio",
  "cash": 100000.0,
  "holdings": 0.0,
  "avg_cost": 0.0,
  "realized_pnl": 0.0,
  "unrealized_pnl": 0.0,
  "total_value": 100000.0
}
After the initial 3 messages, the server also replays the last 200
historical candles as individual `candle` messages. The Alpha Bot
must add each of these to the TickBuffer. This means the bot may
be ready to trade almost immediately after connecting, without
waiting 200 real-time candle closes.
```

### 2.2 Continuous server → bot messages

#### `orderbook` — broadcast every 100 ms

```json
{
  "type": "orderbook",
  "mid": 50234.17,
  "spread": 3.8,
  "ts": 1712000000000000,
  "bids": [[50232.0, 0.42, 3]],
  "asks": [[50235.8, 0.35, 2]]
}
```

Each level: `[price: float, total_quantity: float, order_count: int]`

The `mid` field is the current GBM mid-price. Use this as the reference price
for all indicator calculations and spread quoting.

#### `trade` — on every fill anywhere in the market

```json
{
  "type": "trade",
  "id": 1042,
  "price": 50233.5,
  "qty": 0.025,
  "buyer": "user_1",
  "seller": "mm_bot",
  "ts": 1712000000000000
}
```

The bot's own `user_id` (received in `welcome`) is used to detect if a trade
involves the bot. If `buyer == self.user_id` or `seller == self.user_id`,
this trade filled one of the bot's orders.

#### `candle` — on every 1-second close

```json
{
  "type": "candle",
  "o": 50220.0,
  "h": 50241.8,
  "l": 50218.3,
  "c": 50234.17,
  "v": 3.412,
  "t": 1712000000000
}
```

The Alpha Bot uses candle close prices (`c`) as its price feed for indicators.

#### `portfolio` — after every fill that affects the bot

```json
{
  "type": "portfolio",
  "cash": 95841.2,
  "holdings": 0.08,
  "avg_cost": 50230.0,
  "realized_pnl": 0.0,
  "unrealized_pnl": 3.37,
  "total_value": 100018.07
}
```

Both bots track the server-authoritative portfolio state from this message.
This is the ground truth — do not compute portfolio locally except for
internal decisions.

#### `ack` — order accepted by engine

```json
{ "type": "ack", "order_id": 5531, "status": "accepted", "fills": 1 }
```

`order_id` is a `uint64` integer assigned by the C++ engine.
Store this ID to cancel the order later.
`fills` indicates how many immediate fills occurred (for market orders).

#### `cancel_ack` — cancel result

```json
{ "type": "cancel_ack", "order_id": 5531, "success": true }
```

#### `error` — order rejected

```json
{ "type": "error", "message": "Insufficient cash" }
```

Log the error. Do not crash.

#### `pong` — keepalive response

```json
{ "type": "pong", "ts": 1712000000000 }
```

### 2.3 Bot → server messages

#### Place limit order

```json
{
  "type": "place_order",
  "order_type": "limit",
  "side": "buy",
  "price": 50200.0,
  "qty": 0.05
}
```

#### Place market order

```json
{
  "type": "place_order",
  "order_type": "market",
  "side": "sell",
  "qty": 0.02
}
```

#### Cancel order

```json
{ "type": "cancel_order", "order_id": 5531 }
```

#### Ping keepalive (send every 15 seconds)

```json
{ "type": "ping" }
```

---

## 3. Shared Module Specifications

### 3.1 `bots/requirements.txt`

```
websockets==15.0.1
fastapi==0.115.14
uvicorn==0.34.3
numpy==2.2.6
```

### 3.2 `bots/shared/config.py`

All configuration comes from environment variables with local-dev fallbacks.
This is the Docker-safety contract — never hardcode hostnames.

```python
import os

# Exchange connection
EXCHANGE_WS_URL = os.getenv("EXCHANGE_WS_URL", "ws://127.0.0.1:9001")
# Docker: set EXCHANGE_WS_URL=ws://engine:9001

# Bot HTTP status servers
ALPHA_BOT_PORT  = int(os.getenv("ALPHA_BOT_PORT",  "3001"))
MM_BOT_PORT     = int(os.getenv("MM_BOT_PORT",      "3002"))

# Capital
STARTING_EQUITY = float(os.getenv("STARTING_EQUITY", "100000.0"))

# Alpha bot parameters
ALPHA_RISK_PCT          = float(os.getenv("ALPHA_RISK_PCT",       "0.02"))
ALPHA_STOP_PCT          = float(os.getenv("ALPHA_STOP_PCT",       "0.015"))
ALPHA_TP_PCT            = float(os.getenv("ALPHA_TP_PCT",         "0.030"))
ALPHA_SCORE_THRESHOLD   = float(os.getenv("ALPHA_SCORE_THRESHOLD","0.45"))
ALPHA_DAILY_DRAWDOWN    = float(os.getenv("ALPHA_DAILY_DRAWDOWN", "0.05"))
ALPHA_COOLDOWN_TICKS    = int(os.getenv("ALPHA_COOLDOWN_TICKS",   "10"))
ALPHA_MIN_TICKS         = int(os.getenv("ALPHA_MIN_TICKS",        "40"))
ALPHA_PRICE_WINDOW      = int(os.getenv("ALPHA_PRICE_WINDOW",     "200"))

# Alpha bot indicator periods
EMA_SHORT    = 12
EMA_LONG     = 26
RSI_PERIOD   = 14
MACD_SIGNAL  = 9
BB_PERIOD    = 20

# Market maker parameters
MM_BASE_SPREAD_PCT   = float(os.getenv("MM_BASE_SPREAD_PCT",  "0.0008"))
MM_QUOTE_QTY         = float(os.getenv("MM_QUOTE_QTY",        "0.05"))
MM_MAX_INVENTORY     = float(os.getenv("MM_MAX_INVENTORY",    "0.5"))
MM_INVENTORY_SKEW    = float(os.getenv("MM_INVENTORY_SKEW",   "0.5"))
MM_REQUOTE_INTERVAL  = float(os.getenv("MM_REQUOTE_INTERVAL", "0.5"))
MM_MAX_ORDERS        = int(os.getenv("MM_MAX_ORDERS",         "10"))
```

### 3.3 `bots/shared/exchange_client.py`

This is the single WebSocket connection class used by both bots.
It handles connection, reconnection, message dispatch, and sending.

Implement the following class exactly:

Inside Docker: ws://engine:9001 (service name is "engine")
Outside Docker: ws://localhost:9001

```python
class ExchangeClient:
    """
    Manages one persistent WebSocket connection to ws://localhost:9001.

    Usage:
        client = ExchangeClient(on_message=my_handler)
        await client.run()          # blocks forever, reconnects on drop

    Sending:
        await client.send({"type": "place_order", ...})
        await client.cancel(order_id: int)
        await client.ping()

    The on_message coroutine receives one parsed dict per message.
    """

    def __init__(self, on_message: Callable[[dict], Awaitable[None]]):
        self.on_message   = on_message
        self.user_id: str | None = None
        self._ws          = None           # active websocket connection
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._connected   = asyncio.Event()

    async def run(self):
        """Connect loop with exponential backoff. Never returns."""
        backoff = 1
        while True:
            try:
                async with websockets.connect(EXCHANGE_WS_URL) as ws:
                    self._ws      = ws
                    self._connected.set()
                    backoff       = 1
                    print(f"[ExchangeClient] Connected to {EXCHANGE_WS_URL}")
                    await asyncio.gather(
                        self._recv_loop(ws),
                        self._send_loop(ws),
                        self._keepalive_loop(),
                    )
            except Exception as e:
                self._connected.clear()
                self._ws = None
                print(f"[ExchangeClient] Disconnected: {e} — retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _recv_loop(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "welcome":
                    self.user_id = msg.get("user_id")
                await self.on_message(msg)
            except Exception as e:
                print(f"[ExchangeClient] Message error: {e}")

    async def _send_loop(self, ws):
        while True:
            payload = await self._send_queue.get()
            try:
                await ws.send(json.dumps(payload))
            except Exception as e:
                print(f"[ExchangeClient] Send error: {e}")

    async def _keepalive_loop(self):
        while True:
            await asyncio.sleep(15)
            await self.send({"type": "ping"})

    async def send(self, payload: dict):
        await self._send_queue.put(payload)

        async def place_limit(self, side: str, price: float, qty: float):
        await self.send({
            "type": "place_order",
            "order_type": "limit",
            "side": side,
            "price": round(price, 2),
            "qty": round(qty, 5)    # was 8, now 5
        })

    async def place_market(self, side: str, qty: float):
        await self.send({
            "type": "place_order",
            "order_type": "market",
            "side": side,
            "qty": round(qty, 5)    # was 8, now 5
        })

    async def cancel(self, order_id: int):
        await self.send({
            "type": "cancel_order",
            "order_id": order_id
        })

    async def wait_until_connected(self):
        await self._connected.wait()
```

---

## 4. Alpha Bot — Full Specification

### 4.1 Overview

The Alpha Bot is a trend-following bot that uses four technical indicators
to generate trading signals. It runs a continuous loop driven by candle
close prices received from the exchange.

**Decision pipeline (runs on every candle close):**

```
candle.close → TickBuffer → IndicatorEngine → SignalScorer
    → RiskManager → ExchangeClient → position tracking
```

**Capital:** $100,000 (server-tracked via portfolio messages)
**Asset:** fractional units (qty is float, e.g. 0.05 BTC)
**Price scale:** ~$50,000 per unit

### 4.2 `alpha/tick_buffer.py`

Stores the last `ALPHA_PRICE_WINDOW` (200) candle close prices.
Uses `collections.deque(maxlen=200)`.

```python
class TickBuffer:
    def add(self, price: float) -> None
    def get(self) -> list[float]          # oldest first
    def latest(self) -> float | None
    def is_ready(self) -> bool            # len >= ALPHA_MIN_TICKS (40)
    def size(self) -> int
```

### 4.3 `alpha/indicators.py`

Computes four indicators. Each returns a vote in `[-1.0, +1.0]`.
Uses numpy for array operations.
All methods are pure functions — they take a `list[float]` and return `float`.
Return `0.0` if there is not enough data.

#### Indicator A — EMA Crossover (weight 30%)

```
k_short = 2 / (EMA_SHORT + 1)    where EMA_SHORT = 12
k_long  = 2 / (EMA_LONG  + 1)    where EMA_LONG  = 26

EMA[0]  = prices[0]
EMA[i]  = prices[i] * k + EMA[i-1] * (1 - k)

gap  = ema_short[-1] - ema_long[-1]
vote = +1.0 if gap > 0 else -1.0
```

Minimum data required: EMA_LONG (26) prices.

#### Indicator B — RSI (weight 25%)

```
changes = diff(prices)
gains   = max(change, 0) for each change
losses  = max(-change, 0) for each change

# Seed (simple average of first RSI_PERIOD=14 values)
avg_gain = mean(gains[:14])
avg_loss = mean(losses[:14])

# Wilder smoothing from index 14 onward (alpha = 1/14)
for i in range(14, len(changes)):
    avg_gain = avg_gain * (13/14) + gains[i] * (1/14)
    avg_loss = avg_loss * (13/14) + losses[i] * (1/14)

RS  = avg_gain / avg_loss    (handle avg_loss == 0 → RSI = 100)
RSI = 100 - (100 / (1 + RS))

vote = (50 - RSI) / 50       # clamp to [-1, +1]
```

Minimum data required: RSI_PERIOD + 1 (15) prices.

#### Indicator C — MACD (weight 25%)

```
macd_line   = ema_12 - ema_26            (aligned to same length)
signal_line = EMA(9) of macd_line        (k = 2/(9+1))
histogram   = macd_line[-1] - signal_line[-1]

sign = +1 if histogram > 0 else -1
vote = sign * min(abs(histogram) / 0.5, 1.0)
```

Minimum data required: EMA_LONG + MACD_SIGNAL (35) prices.

#### Indicator D — Bollinger Bands (weight 20%)

```
window = prices[-BB_PERIOD:]     where BB_PERIOD = 20
sma    = mean(window)
std    = population_std(window)  # numpy std with ddof=0

upper  = sma + 2 * std
lower  = sma - 2 * std
pct_b  = (prices[-1] - lower) / (upper - lower)

vote   = (0.5 - pct_b) * 2.0    # clamp to [-1, +1]
```

If std == 0.0, return 0.0.
Minimum data required: BB_PERIOD (20) prices.

#### `IndicatorEngine` class

```python
class IndicatorEngine:
    def compute(self, prices: list[float]) -> dict:
        """
        Returns:
        {
            "ema":       float,   # vote in [-1, +1]
            "rsi":       float,
            "macd":      float,
            "bollinger": float,
        }
        """
```

### 4.4 `alpha/signal_scorer.py`

```python
WEIGHTS = {"ema": 0.30, "rsi": 0.25, "macd": 0.25, "bollinger": 0.20}

class SignalScorer:
    def score(self, votes: dict) -> dict:
        """
        score = weighted sum of votes

        decision:
            score >  ALPHA_SCORE_THRESHOLD (0.45)  → "BUY"
            score < -ALPHA_SCORE_THRESHOLD          → "SELL"
            otherwise                               → "HOLD"

        confidence:
            count indicators that agree with decision direction
            4/4 → 1.00,  3/4 → 0.75,  2/4 → 0.50,  1/4 → 0.25
            HOLD → 0.0

        Returns:
        {
            "score":      float,
            "decision":   str,     # "BUY", "SELL", "HOLD"
            "confidence": float,
            "votes":      dict
        }
        """
```

### 4.5 `alpha/risk_manager.py`

Tracks open position and computes trade sizing.

**Important: asset price is ~$50,000, qty is fractional (e.g. 0.05)**
**All portfolio state comes from server `portfolio` messages.**

```python
class Position:
    entry_price:  float
    quantity:     float      # fractional units, e.g. 0.08
    stop_trigger: float      # entry * (1 - ALPHA_STOP_PCT)
    tp_price:     float      # entry * (1 + ALPHA_TP_PCT)
    tp_order_id:  int | None # integer order ID from ack message

class RiskManager:
    def __init__(self):
        self.equity:   float         = STARTING_EQUITY
        self.position: Position|None = None
        self.cooldown: int           = 0

    def on_portfolio_update(self, msg: dict):
        """
        Called on every 'portfolio' message from the server.
        Updates self.equity from msg['total_value'].
        This is the ground truth — do not calculate equity locally.
        """

    def tick(self):
        """Decrement cooldown by 1 each candle close."""

    def calculate_size(self, entry_price: float, confidence: float,
                       daily_halted: bool) -> float:
        """
        Returns quantity in fractional units (float).

        2% risk rule:
            risk_amount   = equity * ALPHA_RISK_PCT       (0.02)
            stop_distance = entry_price * ALPHA_STOP_PCT  (0.015)
            base_size     = risk_amount / stop_distance

        Cap to 20% of equity in one trade:
            max_affordable = (equity * 0.20) / entry_price
            base_size      = min(base_size, max_affordable)

        Confidence scale:
            final_size = base_size * confidence

        Safety checks (return 0.0 if any fail):
            - position is not None (already in trade)
            - cooldown > 0
            - daily_halted is True
            - final_size < 0.001 (minimum meaningful qty)
            - final_size * entry_price > equity (can't afford)

        Round final_size to 4 decimal places.
        """

    def open_position(self, entry_price: float, quantity: float,
                      tp_order_id: int | None):
        """
        Record that a position is now open.
        stop_trigger = entry_price * (1 - ALPHA_STOP_PCT)
        tp_price     = entry_price * (1 + ALPHA_TP_PCT)
        """

    def close_position(self, exit_price: float, reason: str) -> float:
        """
        Close the position. Return PnL in dollars.
        pnl = (exit_price - entry_price) * quantity
        Set cooldown = ALPHA_COOLDOWN_TICKS.
        Set position = None.
        """

    def should_stop_loss(self, current_price: float) -> bool:
        """True if position is open and current_price <= stop_trigger."""

    def should_reverse_exit(self, decision: str, score: float) -> bool:
        """
        True if position is open AND decision == "SELL" AND score < -0.65.
        This triggers an early exit on strong signal reversal.
        """

    def on_take_profit_filled(self, fill_price: float) -> float:
        """Called when tp_order_id fill arrives. Closes position."""

    def is_flat(self) -> bool
    def get_equity(self) -> float
    def get_position(self) -> Position | None
```

### 4.6 `alpha/drawdown_guard.py`

Identical logic to what was already built and tested. Copy it exactly.
One change: use `ALPHA_DAILY_DRAWDOWN` from config instead of hardcoded value.
`TICKS_PER_DAY = 86_400` (unchanged).

```python
class DrawdownGuard:
    def __init__(self, starting_equity: float)
    def tick(self, current_equity: float) -> bool   # True if breaker just fired
    def is_halted(self) -> bool
    def current_drawdown(self, current_equity: float) -> float   # 0.0 to 1.0
    # internal: _start_new_day(equity)
```

### 4.7 `alpha/kpi_tracker.py`

Identical logic to what was already built and tested. Copy it exactly.

```python
class TradeRecord:
    entry:      float
    exit:       float
    qty:        float      # NOTE: float now, not int (fractional BTC)
    reason:     str
    pnl:        float      # (exit - entry) * qty
    pct_return: float      # (exit - entry) / entry

class KPITracker:
    def record_trade(self, entry, exit_price, qty, reason, new_equity)
    def total_trades(self) -> int
    def total_pnl(self) -> float
    def win_rate(self) -> float
    def sharpe_ratio(self) -> float
    def max_drawdown(self) -> float
    def get_status(self, current_equity: float, position: str) -> dict
```

The `get_status` dict must match this schema exactly (frontend polls it):

```python
{
    "equity":      float,   # current total portfolio value
    "pnl":         float,   # equity - STARTING_EQUITY
    "position":    str,     # "LONG", "SHORT", or "FLAT"
    "trades":      int,
    "winRate":     float,   # 0.0 to 1.0
    "sharpe":      float,
    "maxDrawdown": float    # 0.0 to 1.0
}
```

### 4.8 `alpha/status_server.py`

FastAPI app on `ALPHA_BOT_PORT` (3001).

```python
# Module-level mutable state dict
_state: dict = {
    "equity": 100000.0, "pnl": 0.0, "position": "FLAT",
    "trades": 0, "winRate": 0.0, "sharpe": 0.0, "maxDrawdown": 0.0
}

app = FastAPI(title="Alpha Bot Status")
# Add CORSMiddleware: allow_origins=["*"]

@app.get("/bot/status")
async def bot_status() -> dict:
    return _state

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "bot": "alpha", "port": ALPHA_BOT_PORT}

def update_status(new_state: dict):
    """Called by main.py every tick to push latest numbers."""
    _state.update(new_state)

async def run():
    """Start uvicorn. Called as asyncio.create_task(run())."""
    config = uvicorn.Config(app=app, host="0.0.0.0",
                            port=ALPHA_BOT_PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
```

### 4.9 `alpha/main.py`

This is the entry point and orchestrator. It wires all modules together.

```python
"""
Alpha Bot — main event loop.

Run with:
    python -m alpha.main          (from bots/ directory)

The bot:
    1. Connects to exchange via ExchangeClient
    2. Listens for candle close events as its price feed
    3. On each candle: runs indicators → signal → risk check → order submission
    4. Manages stop-loss by checking price on every orderbook update
    5. Detects take-profit fills via trade messages matching tp_order_id
    6. Runs status HTTP server concurrently on port 3001
"""

class AlphaBot:
    def __init__(self):
        self.client    = ExchangeClient(on_message=self._handle_message)
        self.buffer    = TickBuffer()
        self.indicators = IndicatorEngine()
        self.scorer    = SignalScorer()
        self.risk      = RiskManager()
        self.drawdown  = DrawdownGuard(STARTING_EQUITY)
        self.kpi       = KPITracker()
        self.pending_tp_order_id: int | None = None
        self.latest_mid: float = 0.0       # updated on every orderbook message

    async def run(self):
        await asyncio.gather(
            self.client.run(),
            run_status_server()             # from status_server.py
        )

    async def _handle_message(self, msg: dict):
        # On initial connect, server replays last 200 candles.
        # Buffer these silently — do not trade on historical candles.
        # Use a flag: self._initial_replay_done = False
        # Set to True after first orderbook message arrives
        # (orderbook arrives AFTER candle replay is complete)
        # Only trade on candles received AFTER _initial_replay_done == True
        t = msg.get("type")

        if t == "candle":
            await self._on_candle(msg)

        elif t == "orderbook":
            self.latest_mid = msg.get("mid", self.latest_mid)
            await self._check_stop_loss()   # check on every price update
            self._update_status()

        elif t == "trade":
            await self._on_trade(msg)

        elif t == "portfolio":
            self.risk.on_portfolio_update(msg)

        elif t == "ack":
            await self._on_ack(msg)

        elif t == "error":
            print(f"[AlphaBot] Exchange error: {msg.get('message')}")

    async def _on_candle(self, msg: dict):
        """
        Called on every 1-second candle close.
        This is the main trading decision point.
        """
        close_price = msg["c"]
        self.buffer.add(close_price)
        self.risk.tick()

        # Circuit breaker check
        total_val = self.risk.get_equity()
        circuit_fired = self.drawdown.tick(total_val)
        if circuit_fired:
            await self._emergency_exit("CIRCUIT_BREAKER")
            return

        # Exit checks if in a position
        if not self.risk.is_flat():
            await self._check_signal_reversal(close_price)
            self._update_status()
            return

        # Entry check if flat and buffer is warmed up
        if self.buffer.is_ready() and not self.drawdown.is_halted():
            await self._check_entry(close_price)

        self._update_status()

    async def _check_stop_loss(self):
        """
        Stop-loss is bot-managed (NOT a resting limit order).
        Checked on every orderbook update using latest_mid.
        When triggered:
            1. Cancel resting take-profit limit order (if any)
            2. Place market sell
            3. Close position in risk manager
            4. Record trade in kpi tracker
        """

    async def _check_signal_reversal(self, price: float):
        """
        If bot is LONG and a strong SELL signal fires (score < -0.65):
            1. Cancel resting take-profit
            2. Place market sell
            3. Close position
        Requires buffer.is_ready() to run indicators.
        """

    async def _check_entry(self, price: float):
        """
        Compute indicators → score → decision.
        If decision == "BUY":
            qty = risk.calculate_size(price, confidence, drawdown.is_halted())
            if qty > 0:
                place market buy
                (take-profit limit placed after ack arrives with order_id)
        """

    async def _on_ack(self, msg: dict):
        # If fills > 0 in ack → order was immediately filled (market order)
        # If fills == 0 in ack → order is resting in book (limit order)
        # Use msg.get("fills", 0) > 0 to distinguish
        """
        When we receive an ack for our market buy entry:
            entry_price = latest_mid (best approximation before fill price arrives)
            tp_price    = entry_price * (1 + ALPHA_TP_PCT)
            place limit sell at tp_price for same qty
            (store the ack order_id as pending_entry_ack to match)

        When we receive an ack for our take-profit limit sell:
            store order_id as pending_tp_order_id
            call risk.open_position(entry_price, qty, tp_order_id)

        Implementation note: maintain a small state machine with flags:
            _waiting_for_entry_ack: bool
            _pending_entry_qty: float
            _pending_entry_price: float
        """
         """
        fills == 0 → pure resting limit order, wait for fill via trade message
        fills >= 1 → order was immediately (partially) filled on placement
        For market buy entry: fills will be >= 1 always.
        For take-profit limit sell: fills should be 0 (resting above market).
        """

    async def _on_trade(self, msg: dict):
        """
        Check if this trade fills our take-profit:
            if seller == self.client.user_id AND
               pending_tp_order_id is not None:
                pnl = risk.on_take_profit_filled(msg["price"])
                kpi.record_trade(...)
                pending_tp_order_id = None
        """

    async def _emergency_exit(self, reason: str):
        """Cancel all pending orders and place market sell if in position."""

    def _total_value(self) -> float:
        """
        Returns risk.get_equity() — since portfolio state comes from
        server messages, this is already the total portfolio value.
        """

    def _update_status(self):
        pos = "FLAT"
        if self.risk.get_position():
            pos = "LONG"
        update_status(self.kpi.get_status(self.risk.get_equity(), pos))


async def main():
    bot = AlphaBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Market Maker Bot — Full Specification

### 5.1 Overview

The Market Maker Bot provides liquidity by continuously quoting both sides
of the order book. It profits from the bid-ask spread when both its bid
and ask get filled. It manages inventory risk by skewing its quotes when
it accumulates a directional position.

**Decision pipeline (runs every 500 ms OR on significant price move):**

```
orderbook.mid → SpreadCalculator → cancel old orders
              → InventoryManager (skew) → place new bid + ask
```

**Core parameters:**

```
Base spread:    0.08% each side (total spread = 0.16%)
Quote qty:      0.05 units per side
Max inventory:  0.5 units (long or short)
Requote every:  500 ms
```

### 5.2 `market_maker/inventory_manager.py`

Tracks the bot's current inventory position, updated from server portfolio messages.

```python
class InventoryManager:
    def __init__(self):
        self.holdings:  float = 0.0    # positive = long, negative = short
        self.avg_cost:  float = 0.0
        self.cash:      float = STARTING_EQUITY
        self.total_val: float = STARTING_EQUITY

    def on_portfolio_update(self, msg: dict):
        """Update from server-authoritative portfolio message."""
        self.holdings  = msg["holdings"]
        self.avg_cost  = msg["avg_cost"]
        self.cash      = msg["cash"]
        self.total_val = msg["total_value"]

    def skew_factor(self) -> float:
        """
        Returns a value in [-1.0, +1.0] indicating inventory imbalance.

        skew = holdings / MM_MAX_INVENTORY

        Clamped to [-1, +1].

        Positive skew (too long)  → need to sell → widen bid, tighten ask
        Negative skew (too short) → need to buy  → tighten bid, widen ask
        """

    def is_too_long(self) -> bool:
        return self.holdings >= MM_MAX_INVENTORY

    def is_too_short(self) -> bool:
        return self.holdings <= -MM_MAX_INVENTORY

    def unrealized_pnl(self, mid_price: float) -> float:
        if self.holdings == 0:
            return 0.0
        return (mid_price - self.avg_cost) * self.holdings
```

### 5.3 `market_maker/spread_calculator.py`

Computes the exact bid and ask prices to quote given mid-price and inventory skew.

```python
class SpreadCalculator:
    """
    Base logic (no skew):
        bid = mid * (1 - MM_BASE_SPREAD_PCT)    e.g. mid * 0.9992
        ask = mid * (1 + MM_BASE_SPREAD_PCT)    e.g. mid * 1.0008

    Inventory skew adjustment:
        skew = inventory_manager.skew_factor()   ∈ [-1, +1]

        When skew > 0 (too long, want to sell):
            → push bid DOWN (less willing to buy more)
            → push ask DOWN (more willing to sell)
            bid_offset = MM_BASE_SPREAD_PCT * (1 + skew * MM_INVENTORY_SKEW)
            ask_offset = MM_BASE_SPREAD_PCT * (1 - skew * MM_INVENTORY_SKEW)

        When skew < 0 (too short, want to buy):
            → push bid UP (more willing to buy)
            → push ask UP (less willing to sell)
            bid_offset = MM_BASE_SPREAD_PCT * (1 + skew * MM_INVENTORY_SKEW)
            ask_offset = MM_BASE_SPREAD_PCT * (1 - skew * MM_INVENTORY_SKEW)

        (the same formula handles both cases — skew is signed)

    Quote quantity:
        If too long:  bid_qty = MM_QUOTE_QTY * 0.5   (halve buy qty)
                      ask_qty = MM_QUOTE_QTY           (full sell qty)
        If too short: bid_qty = MM_QUOTE_QTY
                      ask_qty = MM_QUOTE_QTY * 0.5
        Otherwise:    both    = MM_QUOTE_QTY
    """

    def compute(self, mid: float, skew: float, is_too_long: bool,
                is_too_short: bool) -> dict:
        """
        Returns:
        {
            "bid_price": float,
            "ask_price": float,
            "bid_qty":   float,
            "ask_qty":   float,
        }
        All prices rounded to 2 decimal places.
        All quantities rounded to 4 decimal places.
        """
```

### 5.4 `market_maker/order_tracker.py`

Tracks the IDs of the bot's current resting orders so they can be cancelled.

```python
class OrderTracker:
    """
    The MM bot keeps at most 2 active resting orders at any time:
    one bid and one ask. On each requote cycle it cancels both and
    places new ones.
    """

    def __init__(self):
        self._active: dict[int, str] = {}   # order_id → "bid" or "ask"
        self._pending_acks: int = 0         # orders sent but not yet acked

    def on_ack(self, order_id: int):
        """Called when exchange acks a new order."""
        self._active[order_id] = "pending"
        self._pending_acks = max(0, self._pending_acks - 1)

    def on_cancel_ack(self, order_id: int):
        """Called when cancel is confirmed."""
        self._active.pop(order_id, None)

    def on_fill(self, order_id: int):
        """Called when an order is fully filled."""
        self._active.pop(order_id, None)

    def register_sent(self, side: str):
        """Call immediately after sending a place_order (before ack)."""
        self._pending_acks += 1

    def get_all_ids(self) -> list[int]:
        return list(self._active.keys())

    def has_pending(self) -> bool:
        """True if we're waiting for acks — don't requote yet."""
        return self._pending_acks > 0

    def count(self) -> int:
        return len(self._active)

    def clear(self):
        self._active.clear()
        self._pending_acks = 0
```

### 5.5 `market_maker/kpi_tracker.py`

Tracks market maker specific performance metrics.

```python
class MMKPITracker:
    def __init__(self):
        self.total_fills:     int   = 0
        self.total_spread_pnl: float = 0.0   # sum of spread captured
        self.bid_fills:       int   = 0
        self.ask_fills:       int   = 0
        self.equity_curve:    list  = [STARTING_EQUITY]
        self._peak:           float = STARTING_EQUITY

    def on_fill(self, side: str, fill_price: float, qty: float,
                spread_captured: float):
        """
        Called when one of our orders fills.
        side: "bid" or "ask"
        spread_captured: estimated profit from this half of the spread.
            For a bid fill: 0 (we bought, will earn spread when ask fills)
            For an ask fill: (ask_price - bid_price) * qty (round-trip)
            Simplified: just track total fills and let portfolio messages
            give authoritative PnL.
        """
        self.total_fills += 1
        if side == "bid":
            self.bid_fills += 1
        else:
            self.ask_fills += 1

    def record_equity(self, equity: float):
        self.equity_curve.append(equity)
        if equity > self._peak:
            self._peak = equity

    def max_drawdown(self) -> float:
        """Peak-to-trough drawdown across equity_curve."""

    def fill_rate_balance(self) -> float:
        """bid_fills / total_fills. 0.5 = balanced. >0.5 = more buys."""
        if self.total_fills == 0:
            return 0.5
        return self.bid_fills / self.total_fills

    def get_status(self, current_equity: float, holdings: float) -> dict:
        return {
            "equity":         round(current_equity, 2),
            "pnl":            round(current_equity - STARTING_EQUITY, 2),
            "position":       "LONG" if holdings > 0.001
                              else "SHORT" if holdings < -0.001
                              else "FLAT",
            "holdings":       round(holdings, 4),
            "totalFills":     self.total_fills,
            "bidFills":       self.bid_fills,
            "askFills":       self.ask_fills,
            "fillBalance":    round(self.fill_rate_balance(), 4),
            "maxDrawdown":    self.max_drawdown()
        }
```

### 5.6 `market_maker/status_server.py`

Identical structure to alpha/status_server.py but on `MM_BOT_PORT` (3002).

```python
# GET /bot/status  → _state dict
# GET /health      → {"status": "ok", "bot": "market_maker", "port": 3002}

_state: dict = {
    "equity": 100000.0, "pnl": 0.0, "position": "FLAT",
    "holdings": 0.0, "totalFills": 0, "bidFills": 0,
    "askFills": 0, "fillBalance": 0.5, "maxDrawdown": 0.0
}
```

### 5.7 `market_maker/main.py`

```python
"""
Market Maker Bot — main event loop.

Run with:
    python -m market_maker.main      (from bots/ directory)

Requote cycle (every MM_REQUOTE_INTERVAL = 0.5 seconds):
    1. Cancel all active resting orders
    2. Wait for cancel_acks (or timeout after 200ms)
    3. Compute new bid/ask from spread_calculator
    4. Place new limit bid and limit ask
    5. Register both in order_tracker

Event handlers:
    orderbook → update latest_mid, trigger requote if price moved > 0.1%
    trade     → detect our fills, update kpi_tracker
    portfolio → update inventory_manager
    ack       → update order_tracker
    cancel_ack → update order_tracker
"""

class MarketMakerBot:
    def __init__(self):
        self.client    = ExchangeClient(on_message=self._handle_message)
        self.inventory = InventoryManager()
        self.spread    = SpreadCalculator()
        self.tracker   = OrderTracker()
        self.kpi       = MMKPITracker()
        self.latest_mid:    float = 0.0
        self.last_mid_quoted: float = 0.0   # mid at last requote
        self._requote_lock: asyncio.Lock = asyncio.Lock()

    async def run(self):
        await asyncio.gather(
            self.client.run(),
            self._requote_loop(),
            run_status_server()
        )

    async def _requote_loop(self):
        """
        Runs every MM_REQUOTE_INTERVAL seconds.
        Cancels all, then places fresh bid + ask.
        Uses _requote_lock to prevent overlapping cycles.
        """
        await self.client.wait_until_connected()
        await asyncio.sleep(1.0)   # wait for welcome + initial portfolio
        while True:
            await asyncio.sleep(MM_REQUOTE_INTERVAL)
            await self._do_requote()

    async def _do_requote(self):
        """
        Full requote sequence:
        1. If inventory is too long: skip bid (don't buy more)
           If inventory is too short: skip ask (don't sell more)
        2. Cancel all active orders
        3. Compute new quotes
        4. Place bid (if not too long)
        5. Place ask (if not too short)
        6. Update last_mid_quoted
        """
        async with self._requote_lock:
            if self.latest_mid == 0.0:
                return

            # Cancel all active orders
            for oid in self.tracker.get_all_ids():
                await self.client.cancel(oid)

            # Small delay to let cancels propagate
            await asyncio.sleep(0.05)
            self.tracker.clear()

            skew         = self.inventory.skew_factor()
            is_too_long  = self.inventory.is_too_long()
            is_too_short = self.inventory.is_too_short()

            quotes = self.spread.compute(
                self.latest_mid, skew, is_too_long, is_too_short
            )

            if not is_too_long:
                await self.client.place_limit("buy",
                    quotes["bid_price"], quotes["bid_qty"])
                self.tracker.register_sent("bid")

            if not is_too_short:
                await self.client.place_limit("sell",
                    quotes["ask_price"], quotes["ask_qty"])
                self.tracker.register_sent("ask")

            self.last_mid_quoted = self.latest_mid

    async def _handle_message(self, msg: dict):
        t = msg.get("type")

        if t == "orderbook":
            self.latest_mid = msg.get("mid", self.latest_mid)
            # Trigger immediate requote if price moved more than 0.1%
            if self.last_mid_quoted > 0:
                move = abs(self.latest_mid - self.last_mid_quoted) / self.last_mid_quoted
                if move > 0.001:
                    asyncio.create_task(self._do_requote())

        elif t == "trade":
            await self._on_trade(msg)

        elif t == "portfolio":
            self.inventory.on_portfolio_update(msg)
            self.kpi.record_equity(msg["total_value"])
            self._update_status()

        elif t == "ack":
            self.tracker.on_ack(msg["order_id"])

        elif t == "cancel_ack":
            self.tracker.on_cancel_ack(msg["order_id"])

        elif t == "error":
            print(f"[MMBot] Exchange error: {msg.get('message')}")

    async def _on_trade(self, msg: dict):
        """
        Detect fills on our orders by checking:
            buyer  == self.client.user_id  → our bid was filled
            seller == self.client.user_id  → our ask was filled

        On fill:
            order_tracker.on_fill(order_id) — but we don't know order_id
            from trade message directly. Use user_id matching instead.
            Log the fill. KPI portfolio update comes via portfolio message.
        """

    def _update_status(self):
        update_status(self.kpi.get_status(
            self.inventory.total_val,
            self.inventory.holdings
        ))


async def main():
    bot = MarketMakerBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Running Instructions

### Local development (no Docker)

```bash
# From the bots/ directory

# Install dependencies
pip install -r requirements.txt

# Start Alpha Bot
python -m alpha.main

# Start Market Maker Bot (separate terminal)
python -m market_maker.main

# Check status endpoints
curl http://localhost:3001/bot/status    # Alpha Bot
curl http://localhost:3002/bot/status    # Market Maker Bot
```

### Environment variables for Docker

```bash
# Both bots need these
EXCHANGE_WS_URL=ws://engine:9001

# Alpha Bot
ALPHA_BOT_PORT=3001
STARTING_EQUITY=100000

# Market Maker
MM_BOT_PORT=3002
```

---

## 7. Critical Implementation Rules

These are non-negotiable constraints. Violating any of them will cause
runtime failures or incorrect behavior.

1. **Never use `time.sleep()` or blocking calls.** Every wait must be
   `await asyncio.sleep()`. The entire bot runs on one asyncio event loop.

2. **Never compute portfolio state locally.** Always read from the
   `portfolio` message from the server. The server is the ground truth.

3. **order_id is a Python `int`.** It comes from the exchange as a JSON
   number (uint64). Store it as `int`. Never treat it as a string.

4. **qty is a Python `float`.** The asset trades in fractional units
   (e.g. 0.05). Never use `int` for quantity.

5. **All prices must be rounded to 2 decimal places** before sending
   to the exchange.
   All quantities to 5 decimal places (round(qty, 5)).
   All prices to 2 decimal places (round(price, 2)).

6. **The ExchangeClient send queue is non-blocking.** `await client.send()`
   enqueues the message and returns immediately. It does not wait for the
   exchange to process it.

7. **The Alpha Bot stop-loss is bot-managed.** It is NOT a resting limit
   order in the book. It is checked on every `orderbook` message by
   comparing `latest_mid` against `position.stop_trigger`.

8. **The Market Maker Bot must not place orders when inventory limits
   are breached.** If `is_too_long()`, do not place bid. If `is_too_short()`,
   do not place ask.

9. **Both bots must reconnect automatically** on WebSocket disconnect.
   On reconnect, the server assigns a NEW user_id and NEW $100,000 portfolio.
   This means:
   - Reset pending_tp_order_id = None
   - Reset order_tracker
   - Reset inventory_manager holdings to 0.0
   - The bot effectively starts fresh — previous position is lost
     This is acceptable for the competition demo.

10. **Import paths assume bots/ is the working directory.**
    ```python
    from shared.config import *
    from shared.exchange_client import ExchangeClient
    ```
    Run as: `python -m alpha.main` from inside `bots/`.

---

## 8. What Copilot Must NOT Do

- Do not add SQLite, Redis, or any database
- Do not add REST calls to the exchange (it is WebSocket-only)
- Do not use `threading` — asyncio only
- Do not use `requests` — use `websockets` for WS, nothing for HTTP client
- Do not hardcode `localhost` or `9001` — use config.py values
- Do not generate a Dockerfile (that comes later)
- Do not generate docker-compose.yml (that comes later)
- Do not add type: ignore comments or suppress type errors
- Do not generate test files
- Do not add logging configuration beyond simple print statements

---

## 9. Summary Checklist

Copilot must generate exactly these files:

```
bots/requirements.txt                     ✓ 4 packages listed
bots/shared/__init__.py                   ✓ empty
bots/shared/config.py                     ✓ all env vars with fallbacks
bots/shared/exchange_client.py            ✓ ExchangeClient class
bots/alpha/__init__.py                    ✓ empty
bots/alpha/main.py                        ✓ AlphaBot + asyncio.run(main())
bots/alpha/tick_buffer.py                 ✓ TickBuffer class
bots/alpha/indicators.py                  ✓ IndicatorEngine with 4 indicators
bots/alpha/signal_scorer.py              ✓ SignalScorer class
bots/alpha/risk_manager.py               ✓ RiskManager + Position classes
bots/alpha/drawdown_guard.py             ✓ DrawdownGuard class
bots/alpha/kpi_tracker.py                ✓ KPITracker + TradeRecord classes
bots/alpha/status_server.py              ✓ FastAPI on port 3001
bots/market_maker/__init__.py            ✓ empty
bots/market_maker/main.py                ✓ MarketMakerBot + asyncio.run
bots/market_maker/inventory_manager.py   ✓ InventoryManager class
bots/market_maker/spread_calculator.py   ✓ SpreadCalculator class
bots/market_maker/order_tracker.py       ✓ OrderTracker class
bots/market_maker/kpi_tracker.py         ✓ MMKPITracker class
bots/market_maker/status_server.py       ✓ FastAPI on port 3002
```

Total: 20 files.
