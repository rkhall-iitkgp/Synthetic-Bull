# Synthetic-Bull: Bot Management & Admin Dashboard Implementation Plan

## 🎯 Objective
Migrate the `Synthetic-Bull` high-frequency exchange simulator to a fully managed platform supporting authenticated bots, persistent portfolios, and a real-time admin observability dashboard, **without compromising the <1μs tick latency of the C++ engine.**

## 🏗️ Architecture Design (Event-Driven)
To maintain the high performance of the core C++ matching engine, we decouple database writes from the critical trading path:
1.  **Admin/Management API (Node.js/Python)**: Manages SQLite/PostgreSQL for CRUD operations on API keys, bot metadata, and historical logs.
2.  **C++ Engine Firehose**: The engine exposes an admin-only WebSocket feed broadcasting *all* system trades and portfolio updates efficiently.
3.  **Data Logger Worker**: A background process connects to the firehose and asynchronously bulk-inserts trades and KPI metrics to the Database.
4.  **In-Memory Auth & Balances**: C++ engine queries the Admin API (or reads DB directly) on a low-priority thread to maintain a fast lookup table of valid API keys and starting balances.

---

## 💾 Database Schema (SQLite/PostgreSQL)

*   **`Bots`**: 
    *   `id` (UUID/Int)
    *   `name` (String)
    *   `api_key` (String, Indexed)
    *   `status` (String: active, paused)
    *   `created_at` (Timestamp)
*   **`Portfolios`**: 
    *   `bot_id` (FK to Bots)
    *   `cash_balance` (Decimal)
    *   `updated_at` (Timestamp)
*   **`Positions`**: 
    *   `bot_id` (FK to Bots)
    *   `symbol` (String)
    *   `qty` (Decimal)
    *   `avg_entry_price` (Decimal)
*   **`Trades`**: 
    *   `id` (UUID/Int)
    *   `bot_id` (FK to Bots)
    *   `symbol` (String)
    *   `side` (String: buy/sell)
    *   `price` (Decimal)
    *   `qty` (Decimal)
    *   `timestamp` (Timestamp)

---

## 🚀 Step-by-Step Implementation Phases

### Phase 1: Initialize Database & Admin API (The "Control Plane")
1.  Create a new directory `backend/admin_api`.
2.  Set up an Express.js or FastAPI server with a local SQLite database (using Prisma, Sequelize, or SQLAlchemy).
3.  Implement REST endpoints:
    *   `POST /api/bots` -> Generates an API key, creates a DB entry, initializes `Portfolios`.
    *   `GET /api/bots` -> Lists all bots.
    *   `GET /api/bots/:id/trades` -> Fetches trade history for the dashboard.
    *   `GET /api/bots/:id/portfolio` -> Fetches current portfolio state.

### Phase 2: C++ Engine Modifications (Auth & Firehose)
1.  **API Key Management**: On startup (and periodically on a background thread), load valid `api_key`s and balances into an `std::unordered_map` for O(1) auth lookup.
2.  **Auth Requirement**: 
    *   Modify WS `onConnect`. Don't automatically grant $100,000. Wait for an `auth` message.
    *   If `auth` is received and key is valid, spawn the `user_id` session mapped to their DB state.
3.  **Firehose Stream**: Add logic prioritizing an admin connection (authenticated with a master key). The system must broadcast every `trade` event across all users to this one connection.

### Phase 3: Data Logger Worker
1.  Create a background worker script in `backend/admin_api`.
2.  It connects to `ws://localhost:9001` with the master admin API key.
3.  Listens to the incoming stream of `trade` and `portfolio` updates.
4.  Batches and asynchronously writes these records to the `Trades` and `Portfolios` tables in SQLite to provide historical context.

### Phase 4: Bot Client Updates
1.  Update `bots/shared/exchange_client.py`.
2.  Add an argument/environment variable for `BOT_API_KEY`.
3.  Modify the connection lifecycle: immediately after opening the websocket, send the `{"type": "auth", "api_key": "..."}` message before subscribing or sending orders.

### Phase 5: Admin Dashboard (Frontend)
1.  Update `Synthetic-Bull-Frontend`.
2.  **Bot Management Page**: UI to "Create Bot" (calls `POST /api/bots` and shows the generated key). Lists all bots in a table.
3.  **KPI Overview**: Grid showing Net Liq, PnL, Total Trades for all bots fetched via Admin REST API.
4.  **Bot Terminal View**: 
    *   Clicking a bot routes to a detail view.
    *   Fetch historical trades via `GET /api/bots/:id/trades`.
    *   Connect to a specific WebSocket endpoint on the Admin API to stream live trades purely for visualization (acting like a read-only terminal).

---

## 🤖 Bot Interaction Specification

All bots must conform to this flow to access the exchange:

### 1. Authentication (First Message)
Must be sent immediately upon WebSocket connection.
```json
{
  "type": "auth",
  "api_key": "sk_live_123456789abc"
}
```
**Server Responds**: `portfolio` and `open_orders` mapped to the bot's db state.

### 2. Standard Trading
Remains unchanged.
```json
{
  "type": "place_order",
  "symbol": "AAPL",
  "order_type": "limit",
  "side": "buy",
  "price": 180.0,
  "qty": 10.0
}
```

### 3. Subscriptions
After successful auth, bots will automatically receive:
*   Periodic `orderbook` snapshots.
*   Periodic `candle` snapshots.
*   `ack`, `cancel_ack`, `trade`, and `portfolio` events strictly related to their own account.
