# Backend KPI and Session Management Architecture Plan

This document outlines the precise plan to migrate KPI calculations from the individual bots to the centralized Python backend, and to introduce "Session" tracking (both connection-based and lap-timer based) to facilitate accurate, server-side bot performance evaluation.

## 1. Core Objectives
- **Centralized Source of Truth**: Calculate all bot performance metrics (PnL, Win Rate, Drawdown, Sharpe) on the server using raw trades from the C++ Matching Engine.
- **Session Tracking**: Track bot performance over specific timeframes:
  1.  **Connection Sessions**: Automatically started/stopped when a bot connects/disconnects via WebSockets.
  2.  **Lap Sessions**: Explicitly started/stopped via the Admin Dashboard to compare bots over exactly the same conditions or timeframe.
- **Trustless Bots**: The backend should not trust the bot's self-reported PnL or equity.

---

## 2. Database Schema Updates (`models.py`)

To support this, the SQLAlchemy models need to be expanded.

### A. `BotSession` Table
Tracks a specific period of trading for a bot.
- `id` (String, PK, UUID)
- `bot_id` (String, FK to `bots.id`)
- `session_type` (Enum/String: `"connection"` | `"lap"`)
- `status` (Enum/String: `"active"` | `"completed"`)
- `start_time` (DateTime)
- `end_time` (DateTime, nullable)
- `starting_equity` (Float) - Snapshot of bot's total equity at session start.
- `max_equity` (Float) - High-water mark of equity during this session (used for Max Drawdown).
- `min_equity` (Float) - Low-water mark of equity.
- `realized_pnl` (Float, default=0.0) - Cumulative realized PnL during *this* session.

### B. `TradeRound` / `ClosedTrade` Table
Since the C++ engine generates *raw executions* (Trade table), we need a table to store *matched* trades (a full entry and exit cycle) to calculate Win Rate and % Return.
- `id` (String, PK)
- `bot_id` (String, FK)
- `session_id` (String, FK to `BotSession`, nullable)
- `symbol` (String)
- `side` (String: `"long"` | `"short"`)
- `entry_price` (Float)
- `exit_price` (Float)
- `qty` (Float)
- `pnl` (Float)
- `pct_return` (Float)
- `closed_at` (DateTime)

### C. Updates to Existing Tables
- **`Trade` Table**: Add `session_id` (FK, nullable) to associate a raw execution mapped during a lap/connection.
- **`Position` Table**: Add `unrealized_pnl` (to cache current calculations).

---

## 3. Implementation Phases

### Phase 1: Session Management API and Hooks
1. **WebSocket Integration (`admin_api/main.py`)**: 
   - On `websocket.accept()`: Create a new `BotSession` (type: `"connection"`), record the bot's current `starting_equity`. Store `session_id` in `active_connections`.
   - On `WebSocketDisconnect`: Update the `BotSession` `status` to `"completed"` and stamp `end_time`.
2. **Lap API Endpoints**:
   - `POST /api/bots/{bot_id}/sessions/start`: Creates a `BotSession` (type: `"lap"`).
   - `POST /api/bots/{bot_id}/sessions/stop`: Ends the lap session.
   - `GET /api/bots/{bot_id}/sessions`: List all sessions for a bot.

### Phase 2: The FIFO Trade Matcher
A bot's Win Rate is based on closed positions (e.g., Buy 10 AAPL, then Sell 10 AAPL).
1. Create a Python background worker/service that listens to new `Trade` inserts.
2. **FIFO Algorithm**:
   - Maintain a queue of open raw trades per bot/symbol.
   - When an opposing trade arrives (e.g., Sell order while holding Long), match the quantities.
   - Calculate the `realized_pnl` and `pct_return` of the matched quantity.
   - Insert a row into `TradeRound`.
   - Update the active `BotSession`'s aggregate `realized_pnl`.

### Phase 3: Real-Time Equity and Max Drawdown
To calculate true Max Drawdown, the backend must track unrealized equity dips between trades.
1. **Price Feed**: The C++ `MatchingEngine` or `MarketSimulator` must publish current Market Prices (e.g., Best Bid/Ask midpoint) to a message queue (Redis/ZeroMQ) that the Python backend listens to.
2. **Equity Updater Worker**:
   - Periodically (e.g., every 1 second) or tick-by-tick, calculate the current equity for all bots with `"active"` sessions.
   - `Current Equity = Cash Balance + Sum(Position Qty * (Current Market Price - Avg Entry Price))`
   - Update the active `BotSession`:
     - If `Current Equity > max_equity`, update `max_equity`.
     - `Current Drawdown = (max_equity - Current Equity) / max_equity`
3. This completely removes the need for the bot's local `KPITracker._equity_curve`.

### Phase 4: Reading KPIs (Admin Dashboard)
1. **Endpoint `GET /api/sessions/{session_id}/kpi`**:
   - **Win Rate**: `COUNT(TradeRound where pnl > 0) / COUNT(TradeRound)`.
   - **Realized PnL**: Sum of `TradeRound.pnl`.
   - **Max Drawdown**: `(max_equity - min_equity) / max_equity` (or derived from live equity tracker).
   - **Sharpe Ratio**: Calculated using the standard deviation of `TradeRound.pct_return`.

---

## 4. Next Steps for Implementation
1. **Apply SQLAlchemy changes** to `models.py` and `schemas.py`.
2. **Implement WebSocket Connect/Disconnect hooks** to create connection sessions.
3. **Build the FIFO Trade Matcher** in `worker.py` to convert raw trades to `TradeRound` entries.
4. **Implement real-time price consumer** to update `max_equity` for drawdown calculations.