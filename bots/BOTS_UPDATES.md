# BOTS MODULE — Update Instructions

## Synthetic-Bull | Multi-Symbol Backend Integration

## IIT Kharagpur × NextBull OpenSoft 2026

> This document lists **only the changes** to apply to the already-generated
> `bots/` module. The original `BOTS_README.md` was written against a
> single-symbol backend. The actual backend is multi-symbol (10 assets)
> with a different protocol. Apply every change in this file exactly as written.
> Do not regenerate files from scratch — only modify what is listed here.

---

## CHANGE 1 — `shared/config.py`

### Add these new variables to the bottom of the existing file

```python
# ── Symbol Selection ───────────────────────────────────────────────────────
# Alpha Bot trades ONE symbol. BTC recommended (highest volatility, most signals)
ALPHA_SYMBOL  = os.getenv("ALPHA_SYMBOL", "BTC")

# Market Maker Bot trades ONE symbol. AAPL recommended (stable, low vol)
MM_SYMBOL     = os.getenv("MM_SYMBOL", "AAPL")

# Minimum order quantity per symbol
# BTC/ETH: 0.001 (fractional), Stocks: 1.0 (whole shares)
ALPHA_MIN_QTY = float(os.getenv("ALPHA_MIN_QTY", "0.001"))
MM_MIN_QTY    = float(os.getenv("MM_MIN_QTY",    "0.001"))
```

---

## CHANGE 2 — `shared/exchange_client.py`

### Three method signatures change — add `symbol: str` parameter

Replace the existing `place_limit`, `place_market`, and `cancel` methods
with these updated versions:

```python
async def place_limit(self, symbol: str, side: str, price: float, qty: float):
    """side: 'buy' or 'sell'"""
    await self.send({
        "type":       "place_order",
        "symbol":     symbol,
        "order_type": "limit",
        "side":       side,
        "price":      round(price, 2),
        "qty":        round(qty, 5)
    })

async def place_market(self, symbol: str, side: str, qty: float):
    await self.send({
        "type":       "place_order",
        "symbol":     symbol,
        "order_type": "market",
        "side":       side,
        "qty":        round(qty, 5)
    })

async def cancel(self, symbol: str, order_id: int):
    await self.send({
        "type":     "cancel_order",
        "symbol":   symbol,
        "order_id": order_id
    })
```

### Also update `_recv_loop` — add `open_orders` to the welcome sequence

The `_recv_loop` method does not need changes — it already dispatches every
message to `on_message`. No structural change needed here.

### Add `get_initial_price` helper method to ExchangeClient

```python
def get_initial_price(self, symbol: str) -> float | None:
    """
    Returns the initial price of a symbol from the welcome message.
    Returns None if welcome has not been received yet.
    Populated when welcome message arrives in _recv_loop.
    """
    return self._symbol_prices.get(symbol)
```

And add to `__init__`:

```python
self._symbol_prices: dict[str, float] = {}
```

And in `_recv_loop`, inside the `if msg.get("type") == "welcome":` block,
add:

```python
# Parse multi-symbol welcome format
# welcome = {"type": "welcome", "user_id": "user_1",
#             "symbols": [{"symbol": "BTC", "price": 50234.17}, ...]}
for entry in msg.get("symbols", []):
    self._symbol_prices[entry["symbol"]] = entry["price"]
```

---

## CHANGE 3 — `alpha/main.py`

### Add symbol filter to ALL message handlers

At the top of the `AlphaBot` class `__init__`, add:

```python
self.symbol: str = ALPHA_SYMBOL    # imported from shared.config
```

Replace the `_handle_message` method with this version:

```python
async def _handle_message(self, msg: dict):
    t = msg.get("type")

    # ── Symbol-agnostic messages ──────────────────────────────────────────
    if t == "welcome":
        # New format: {"type": "welcome", "user_id": "...",
        #              "symbols": [{"symbol": "BTC", "price": ...}, ...]}
        self.client.user_id = msg.get("user_id")
        # Initial price is available via client.get_initial_price(self.symbol)
        return

    if t == "portfolio":
        self.risk.on_portfolio_update(msg)
        return

    if t == "open_orders":
        await self._on_open_orders(msg)
        return

    if t == "error":
        print(f"[AlphaBot] Exchange error: {msg.get('message')}")
        return

    if t == "pong":
        return

    # ── Symbol-specific messages — IGNORE if not our symbol ──────────────
    if msg.get("symbol") != self.symbol:
        return

    if t == "candle":
        await self._on_candle(msg)

    elif t == "orderbook":
        self.latest_mid = msg.get("mid", self.latest_mid)
        await self._check_stop_loss()
        self._update_status()

    elif t == "trade":
        await self._on_trade(msg)

    elif t == "ack":
        await self._on_ack(msg)

    elif t == "cancel_ack":
        pass    # no action needed for alpha bot cancel acks
```

### Add `_on_open_orders` method to AlphaBot

```python
async def _on_open_orders(self, msg: dict):
    """
    Received on connect and after every order/cancel action.
    Used to restore state after a reconnect.

    Scan for any resting orders belonging to our symbol.
    If a take-profit order is found (side='sell'), restore
    pending_tp_order_id so stop-loss logic can cancel it.

    Format:
    {
        "type": "open_orders",
        "orders": [
            {"order_id": 5531, "symbol": "BTC", "side": "sell",
             "price": 51500.0, "orig_qty": 0.05, "remaining_qty": 0.05}
        ]
    }
    """
    orders = msg.get("orders", [])
    for o in orders:
        if o.get("symbol") != self.symbol:
            continue
        if o.get("side") == "sell" and self.pending_tp_order_id is None:
            # Restore take-profit tracking after reconnect
            self.pending_tp_order_id = o["order_id"]
            print(f"[AlphaBot] Restored TP order {o['order_id']} "
                  f"@ {o['price']} from open_orders")
```

### Update all `client.place_limit`, `client.place_market`, `client.cancel` calls

Every call to these methods now requires `self.symbol` as the first argument.

Find and replace:

```python
# OLD
await self.client.place_market("buy", quantity)
await self.client.place_market("sell", position.quantity)
await self.client.place_limit("sell", quantity, tp_price)
await self.client.cancel(self.pending_tp_order_id)

# NEW
await self.client.place_market(self.symbol, "buy", quantity)
await self.client.place_market(self.symbol, "sell", position.quantity)
await self.client.place_limit(self.symbol, "sell", tp_price, quantity)
await self.client.cancel(self.symbol, self.pending_tp_order_id)
```

Note: `place_limit` argument order is `(symbol, side, price, qty)` —
make sure price comes before qty in all calls.

---

## CHANGE 4 — `alpha/risk_manager.py`

### Update `on_portfolio_update` for multi-symbol portfolio format

Replace the existing `on_portfolio_update` method with:

```python
def on_portfolio_update(self, msg: dict):
    """
    Multi-symbol portfolio format:
    {
        "type": "portfolio",
        "cash": 95841.20,
        "total_value": 100018.07,
        "positions": {
            "BTC": {
                "holdings": 0.08,
                "avg_cost": 50230.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 3.37
            }
        }
    }

    self.equity is updated from total_value (cash + all positions).
    This is the ground truth from the server.
    """
    self.equity = msg.get("total_value", self.equity)

    # Extract our symbol's position if available
    positions = msg.get("positions", {})
    my_pos    = positions.get(self.symbol, {})
    # Store for reference (used by _total_value in main.py)
    self._server_holdings  = my_pos.get("holdings",      0.0)
    self._server_avg_cost  = my_pos.get("avg_cost",       0.0)
    self._server_unreal_pnl = my_pos.get("unrealized_pnl", 0.0)
```

Also add `self.symbol` to `RiskManager.__init__`:

```python
def __init__(self, symbol: str):
    self.symbol = symbol
    self.equity  = STARTING_EQUITY
    self.position: Position | None = None
    self.cooldown: int = 0
    self._server_holdings:   float = 0.0
    self._server_avg_cost:   float = 0.0
    self._server_unreal_pnl: float = 0.0
```

And update `AlphaBot.__init__` to pass symbol:

```python
self.risk = RiskManager(symbol=ALPHA_SYMBOL)
```

---

## CHANGE 5 — `market_maker/main.py`

### Add symbol filter and open_orders handler

At the top of `MarketMakerBot.__init__`, add:

```python
self.symbol: str = MM_SYMBOL    # imported from shared.config
```

Replace the `_handle_message` method with:

```python
async def _handle_message(self, msg: dict):
    t = msg.get("type")

    # ── Symbol-agnostic ───────────────────────────────────────────────────
    if t == "welcome":
        self.client.user_id = msg.get("user_id")
        return

    if t == "portfolio":
        self.inventory.on_portfolio_update(msg)
        self.kpi.record_equity(msg["total_value"])
        self._update_status()
        return

    if t == "open_orders":
        await self._on_open_orders(msg)
        return

    if t == "error":
        print(f"[MMBot] Exchange error: {msg.get('message')}")
        return

    if t == "pong":
        return

    # ── Symbol-specific — IGNORE if not our symbol ────────────────────────
    if msg.get("symbol") != self.symbol:
        return

    if t == "orderbook":
        self.latest_mid = msg.get("mid", self.latest_mid)
        if self.last_mid_quoted > 0:
            move = abs(self.latest_mid - self.last_mid_quoted) / self.last_mid_quoted
            if move > 0.001:
                asyncio.create_task(self._do_requote())

    elif t == "trade":
        await self._on_trade(msg)

    elif t == "ack":
        self.tracker.on_ack(msg["order_id"])

    elif t == "cancel_ack":
        self.tracker.on_cancel_ack(msg["order_id"])
```

### Add `_on_open_orders` method to MarketMakerBot

```python
async def _on_open_orders(self, msg: dict):
    """
    On connect (or after reconnect), restore order_tracker
    with any existing resting orders for our symbol.
    This prevents the bot from placing duplicate orders
    on top of ones that survived the reconnect.

    Format same as alpha bot — see CHANGE 3 above.
    """
    orders = msg.get("orders", [])
    self.tracker.clear()
    for o in orders:
        if o.get("symbol") != self.symbol:
            continue
        self.tracker.on_ack(o["order_id"])
        print(f"[MMBot] Restored order {o['order_id']} "
              f"{o['side']} @ {o['price']} from open_orders")
```

### Update all `client.place_limit` and `client.cancel` calls in `_do_requote`

```python
# OLD
await self.client.place_limit("buy",  quotes["bid_price"], quotes["bid_qty"])
await self.client.place_limit("sell", quotes["ask_price"], quotes["ask_qty"])
await self.client.cancel(oid)

# NEW
await self.client.place_limit(self.symbol, "buy",  quotes["bid_price"], quotes["bid_qty"])
await self.client.place_limit(self.symbol, "sell", quotes["ask_price"], quotes["ask_qty"])
await self.client.cancel(self.symbol, oid)
```

---

## CHANGE 6 — `market_maker/inventory_manager.py`

### Update `on_portfolio_update` for multi-symbol format

Replace the existing `on_portfolio_update` method with:

```python
def on_portfolio_update(self, msg: dict):
    """
    Multi-symbol portfolio format. Extract only our symbol's position.
    """
    self.cash      = msg.get("cash",        self.cash)
    self.total_val = msg.get("total_value", self.total_val)

    positions = msg.get("positions", {})
    my_pos    = positions.get(self.symbol, {})

    self.holdings = my_pos.get("holdings",  0.0)
    self.avg_cost = my_pos.get("avg_cost",  0.0)
```

Also add `self.symbol` to `InventoryManager.__init__`:

```python
def __init__(self, symbol: str):
    self.symbol    = symbol
    self.holdings  = 0.0
    self.avg_cost  = 0.0
    self.cash      = STARTING_EQUITY
    self.total_val = STARTING_EQUITY
```

And update `MarketMakerBot.__init__`:

```python
self.inventory = InventoryManager(symbol=MM_SYMBOL)
```

---

## CHANGE 7 — Both `status_server.py` files

### No code changes needed

Both status servers (port 3001 and 3002) are unaffected by multi-symbol
changes. They serve data pushed by `_update_status()` which is already
symbol-aware after the changes above.

---

## CHANGE 8 — `alpha/tick_buffer.py`, `alpha/indicators.py`,

## `alpha/signal_scorer.py`, `alpha/drawdown_guard.py`,

## `alpha/kpi_tracker.py`

### No changes needed

These files are pure math with no protocol dependency.
They are unaffected by multi-symbol changes.

---

## CHANGE 9 — `market_maker/spread_calculator.py`,

## `market_maker/order_tracker.py`,

## `market_maker/kpi_tracker.py`

### No changes needed

These files operate only on prices and quantities.
They have no protocol dependency.

---

## Summary — Files That Change

| File                                | Changes                                                                                              |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `shared/config.py`                  | Add ALPHA_SYMBOL, MM_SYMBOL, ALPHA_MIN_QTY, MM_MIN_QTY                                               |
| `shared/exchange_client.py`         | Add symbol param to place_limit/place_market/cancel; update welcome parser; add \_symbol_prices dict |
| `alpha/main.py`                     | Add symbol filter; add \_on_open_orders; update all client calls                                     |
| `alpha/risk_manager.py`             | Update on_portfolio_update; add symbol to **init**                                                   |
| `market_maker/main.py`              | Add symbol filter; add \_on_open_orders; update all client calls                                     |
| `market_maker/inventory_manager.py` | Update on_portfolio_update; add symbol to **init**                                                   |

## Files That Do NOT Change

```
shared/__init__.py
alpha/__init__.py
alpha/tick_buffer.py
alpha/indicators.py
alpha/signal_scorer.py
alpha/drawdown_guard.py
alpha/kpi_tracker.py
alpha/status_server.py
market_maker/__init__.py
market_maker/spread_calculator.py
market_maker/order_tracker.py
market_maker/kpi_tracker.py
market_maker/status_server.py
requirements.txt
```

---

## Critical Rules — New Additions

### Rule 11 — Filter all messages by symbol

Every `orderbook`, `trade`, `candle`, `ack`, `cancel_ack` handler must
check `msg.get("symbol") == self.symbol` before processing.
The bot receives messages for all 10 symbols simultaneously.
Without filtering, indicator prices will be a random mix of BTC, AAPL,
TSLA etc. — completely corrupting all signals.

### Rule 12 — Rate limit awareness

Server enforces 50 messages/second per connection.
Alpha Bot: max 3 messages per candle (1 second) — safely within budget.
Market Maker Bot: max 4 messages per requote (every 500ms) = 8/sec — within budget.
Do NOT add sleep() calls to throttle — both bots are naturally within limits.

### Rule 13 — welcome message format changed

Old: `{"type": "welcome", "user_id": "u1", "price": 50234.17}`
New: `{"type": "welcome", "user_id": "u1", "symbols": [{"symbol": "BTC", "price": 50234.17}, ...]}`
Never read `msg["price"]` from welcome — it no longer exists.
Always read price from `client.get_initial_price(self.symbol)`.

### Rule 14 — open_orders is the reconnect mechanism

On every reconnect the server sends `open_orders` before any other data.
Both bots must restore their state from this message, not from local memory.
Local memory is wiped on reconnect. open_orders is the server's authoritative
list of what orders are still alive.

### Rule 15 — place_order and cancel_order require symbol field

Every order message sent to the exchange must include `"symbol": self.symbol`.
Orders without a symbol field will be rejected with an error message.
