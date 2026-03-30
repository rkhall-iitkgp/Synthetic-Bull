# Synthetic Bull — Bot Architecture & Authentication Guide

This document outlines the complete lifecycle of bot management, API key distribution, and data flow within the Synthetic Bull platform. It explains how bots authenticate with the matching engine, how their trades are securely tracked, and how to properly configure them.

---

## 1. System Overview

The platform is designed to handle multiple autonomous trading bots securely. The architecture is split into three main areas concerning bots:
1. **Admin REST API (Port 8000):** Manages bot identities, generates API keys, and serves portfolio/trade data to the React dashboard.
2. **Matching Engine (Port 9001):** A high-performance C++ WebSocket server. It enforces authentication, matching orders, and broadcasting market data.
3. **Bot Instances:** Python-based scripts that connect to the engine via WebSockets, consume market data, and send order signals.

---

## 2. Bot Identity & API Key Generation

Bots cannot trade without a registered identity and a valid API key.

1. **Provisioning:**
   When an admin provisions a new bot via the React Dashboard (`/admin/dashboard`), the Admin API generates a cryptographic token using Python's `secrets` module (e.g., `sk_live_661fc3e26202...`).
2. **Database Storage:**
   The Admin API creates a new SQLite record in the `bots` table containing a unique `bot_id` (UUID), the user-friendly bot name, and the generated `api_key`.
3. **Cross-Service Synchronization:**
   The C++ Matching Engine runs a background thread (`authPollingThread()`) that constantly queries the shared SQLite database (`admin.db`) every 2 seconds. This ensures that the engine's in-memory authentication map (`g_valid_keys`) is always up to date with newly created API keys, without needing a restart.

---

## 3. The Authentication Flow (Engine Connection)

When a bot script is executed, it establishes a persistent WebSocket connection to the engine at `ws://127.0.0.1:9001`.

1. **Initial Handshake:** 
   Upon connection, the engine initially classifies the connection as an unauthenticated guest (assigned the ID `"sim_bot"`). This allows read-only frontend components to view the public orderbook.
2. **Auth Payload:** 
   The bot's `ExchangeClient` immediately sends an authentication payload containing its API key:
   ```json
   { "type": "auth", "api_key": "sk_live_..." }
   ```
3. **Validation & Role Assignment:**
   The C++ engine intercepts the `"auth"` message and checks the provided `api_key` against its synchronized `g_valid_keys` map. 
   * If valid, it retrieves the associated `bot_id`. 
   * It then modifies the socket's internal state (`data->user_id = bot_id` and `data->is_authenticated = true`).
4. **Execution Permissions:**
   Any further `"place_order"` or `"cancel_order"` events sent down that WebSocket connection are mathematically bound to that specific `bot_id`. If a bot attempts to trade without authenticating, the engine rejects the order with a `"Not authenticated"` error.

---

## 4. Trade Logging & The "Admin Firehose"

To populate the Admin Dashboard with historical trade data and dynamic portfolios, the Admin API relies on a background worker (`worker.py`).

1. **The God Key:** 
   The data logger worker authenticates with the C++ engine using a hardcoded master key (`sk_admin_12345`).
2. **The Firehose:**
   When the engine detects the admin key, it subscribes the worker to a privileged WebSocket channel called `"admin_firehose"`.
3. **Data Interception:** 
   Every time an order matches in the engine, a `Trade` structurally containing the `buyer_id` and `seller_id` is generated. The engine broadcasts this trade down the firehose.
4. **Deduplication & Storage:**
   The worker intercepts the trade, ensures it hasn't already processed it via parallel channels (using a fast ID-based deduplication cache), and writes it securely to the `trades` table in the SQLite database.
   * *Note: Trades involving `"sim_bot"` (unauthenticated UI testing) are intentionally dropped and not saved to the database.*

---

## 5. Configuring and Running Bots

Because the bots are independent processes, they require the environment to be configured before execution. We use environment variables to ensure different bot instances can share the same source code without conflicts.

### A. Environment Setup

* **Windows:**
  ```powershell
  cd "C:\path\to\Synthetic-Bull"
  $env:BOT_API_KEY="sk_live_..."
  $env:EXCHANGE_WS_URL="ws://127.0.0.1:9001"
  ```
* **Linux / macOS:**
  ```bash
  export BOT_API_KEY="sk_live_..."
  export EXCHANGE_WS_URL="ws://127.0.0.1:9001"
  ```

Alternatively, for quick testing, you can paste the API key directly into `bots/shared/config.py` at the `BOT_API_KEY` assignment line.

### B. Execution

Once the API key is bound to the terminal session, run the bot as a Python module from the *root* `Synthetic-Bull` directory. This allows Python to correctly resolve the `bots.shared` and strategy namespaces.

**Starting the Alpha Bot (Trend Following):**
```powershell
python -m bots.alpha.main
```

**Starting the Market Maker Bot (Liquidity Provision - requires a separate terminal):**
```powershell
# Set a distinct API key generated from the dashboard for this bot
$env:BOT_API_KEY="sk_live_DIFFERENT_KEY"
python -m bots.market_maker.main
```

As long as the API keys are correct, they will authenticate cleanly, their orders will be tagged with their unique database IDs, and their real-time performance will be immediately visible on the React Admin Dashboard.