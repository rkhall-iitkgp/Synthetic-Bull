# Synthetic-Bull — Module 1: C++ Core Engine

> A high-performance, multi-symbol exchange simulator built in C++ with institutional-grade stochastic pricing models and real-time WebSocket streaming.

---

## Features

### 🔬 Advanced Price Simulation (Heston + Merton)

The engine uses **Geometric Brownian Motion (GBM) as its base model**, enhanced with two industry-standard extensions:

| Model | What it does | Real-world equivalent |
|-------|-------------|----------------------|
| **Heston Stochastic Volatility** | σ itself evolves over time with mean-reversion (κ), vol-of-vol (ξ), and a leverage effect (ρ < 0 means price drops → vol spikes) | VIX spikes during sell-offs |
| **Merton Jump Diffusion** | Poisson-sampled sudden price gaps with configurable intensity (λ), mean jump size (μ_J), and jump std (σ_J) | Earnings announcements, flash crashes |
| **Jump Compensation** | Drift-adjusted by `λ(e^{μ_J + σ_J²/2} - 1)` to prevent long-term price drift from jumps | Martingale correction |
| **Circuit Breaker** | Single-tick moves capped at ±2% | Exchange halt protection |
| **Sector Correlation** | 3 independent sector factors (tech, financial, crypto) with per-symbol beta loading | Sector co-movement without cross-sector noise |

### 📊 Smart Market Making

The built-in `sim_bot` acts as an **inventory-aware, asymmetric market maker**:

- **Quote Skewing**: If the bot accumulates too much long inventory, it tightens asks and widens bids to encourage selling.
- **Dynamic Spread**: Spread widens automatically when instantaneous volatility exceeds the long-run level: `spread × clamp(√v / σ_long, 0.5, 4.0)`.
- **Volume Clustering**: A log-normal activity multiplier (clamped 0.2–5.0×) creates realistic bursts of high/low trading activity.
- **Inventory Limits**: Configurable per-symbol. The bot reduces or stops quoting on one side when approaching its position limit. Can be **toggled off** entirely via `use_inventory_limit = false` in the symbol config.

### 🛡️ Production Safety

- **Rate Limiting**: Token bucket per connection (50 msgs/sec, burst 50). Prevents order spam during demos while allowing market making bots.
- **Open Orders Tracking**: Server tracks all resting limit orders per user. Sent as `open_orders` message on connect and after every order/cancel action.
- **Capital Checks**: Buy orders are rejected if the user lacks sufficient cash.

### ⚡ Performance

- **10 symbols × 50 ticks/sec** sustained throughput
- **<1μs overhead** per tick from all advanced features
- **Multi-thread architecture**: event loop, simulator threads, broadcaster, sector factor generator
- **3-second warmup** fills order books before accepting connections

### 📈 Multi-Symbol Mathematical Parameters

To guarantee realistic price action, each asset is tuned with specific Heston (κ, ξ, ρ) and Merton Jump (λ, μ_J, σ_J) parameters alongside sector beta (β) loadings:

| Symbol | Sector | Initial Price | σ (Base Vol) | κ (Mean-Rev) | ξ (Vol-of-Vol) | ρ (Leverage) | λ (Jump Int) | μ_J (Jump Mean) | σ_J (Jump Std) | β (Sector Beta) |
|--------|--------|--------------|--------------|--------------|---------------|-------------|-------------|----------------|---------------|---------------|
| **AAPL** | Tech | $185.00 | 0.015 | 2.0 | 0.08 | -0.60 | 0.3 | 0.0 | 0.020 | 0.50 |
| **GOOGL**| Tech | $175.00 | 0.014 | 2.5 | 0.07 | -0.50 | 0.2 | 0.0 | 0.015 | 0.45 |
| **MSFT** | Tech | $420.00 | 0.013 | 2.5 | 0.06 | -0.50 | 0.2 | 0.0 | 0.015 | 0.50 |
| **AMZN** | Tech | $185.00 | 0.016 | 2.0 | 0.09 | -0.55 | 0.3 | 0.0 | 0.020 | 0.40 |
| **TSLA** | Tech | $250.00 | 0.035 | 1.5 | 0.30 | -0.70 | 0.6 | 0.0 | 0.040 | 0.60 |
| **META** | Tech | $500.00 | 0.018 | 2.0 | 0.10 | -0.55 | 0.3 | 0.0 | 0.025 | 0.40 |
| **NVDA** | Tech | $880.00 | 0.030 | 1.8 | 0.25 | -0.65 | 0.5 | 0.0 | 0.035 | 0.45 |
| **JPM**  | Fin | $195.00 | 0.010 | 3.0 | 0.05 | -0.30 | 0.1 | 0.0 | 0.010 | 0.55 |
| **BTC**  | Crypto | $50000 | 0.025 | 1.0 | 0.35 | -0.40 | 0.8 | 0.0 | 0.050 | 0.70 |
| **ETH**  | Crypto | $3500.0| 0.028 | 1.0 | 0.38 | -0.40 | 0.9 | 0.0 | 0.055 | 0.65 |

> **Note on θ (Long-Run Variance):** θ = σ² for all symbols — the stochastic variance evolving via the Heston CIR process strictly mean-reverts to the square of the base volatility (σ).

> **Note on μ_J = 0 (Symmetric Jumps):** Jump means are set to zero to ensure no systematic directional price bias from the jump process. Fat tails and realistic crash/spike patterns are generated purely from jump standard deviation (σ_J). This is the standard calibration for market-neutral simulation.

### ⏱️ Time Step Calibration (dt_)

The model time step `dt_` controls how fast simulated time advances relative to wall-clock time. Each simulator tick fires every 20ms (50 ticks/sec).

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `dt_` | 0.00008 | ≈1 trading-second per tick (annualized) |
| Ticks/sec | 50 | = 50 trading-seconds per real-second |
| 1 real minute | = ~50 trading-minutes | Visible intraday price action |
| 1 real hour | ≈ 1 trading-day | Full daily range compressed into ~6.5 min |

With `dt_ = 0.00008` and `σ = 0.015` (AAPL), the per-tick standard deviation is:
```
std_dev = σ × √dt ≈ 0.015 × 0.00894 ≈ 0.013%
```
This produces smooth, realistic price movements that remain stable indefinitely — prices naturally oscillate around their initial levels via the Heston mean-reversion mechanism.

---

## Build & Run

### Prerequisites
- C++17 compiler (clang++ or g++)
- CMake ≥ 3.14
- OpenSSL, zlib

### Local Build
```bash
cd backend
mkdir -p build && cd build
cmake ..
make -j$(nproc)
cd ..
./build/SyntheticBull
```

### Docker
```bash
docker-compose up --build
```

---

## WebSocket API Reference

Connect to: **`ws://localhost:9001`** (or `ws://engine:9001` in Docker)

### Connection Lifecycle
```
1. Client connects
2. Server sends: welcome (user_id, all symbols + prices)
3. Server sends: per-symbol orderbook snapshots (top 20 levels)
4. Server sends: per-symbol last 200 candles (chart history)
5. Server sends: portfolio (initial $100,000)
6. Server sends: open_orders (empty on fresh connect)
7. Ongoing: orderbook snapshots every 100ms
8. Ongoing: trade events on every fill
9. Ongoing: candle events every 1 second
```

### Server → Client Messages

| Type | When | Key Fields |
|------|------|-----------|
| `welcome` | On connect | `user_id`, `symbols[{symbol, price}]` |
| `orderbook` | Every 100ms per symbol | `symbol`, `mid`, `spread`, `bids[]`, `asks[]` |
| `trade` | On every fill | `symbol`, `price`, `qty`, `buyer`, `seller` |
| `candle` | Every 1s per symbol | `symbol`, `o`, `h`, `l`, `c`, `v`, `t` |
| `portfolio` | On connect + after fills | `cash`, `total_value`, `positions{symbol: {...}}` |
| `open_orders` | On connect + after order/cancel | `orders[{order_id, symbol, side, price, orig_qty, remaining_qty}]` |
| `ack` | After order accepted | `symbol`, `order_id`, `status`, `fills` |
| `cancel_ack` | After cancel request | `symbol`, `order_id`, `success` |
| `error` | On validation/rate limit failure | `message` |
| `pong` | After ping | `ts` |
| `symbols` | After get_symbols | `symbols[{symbol, price}]` |

#### `open_orders` payload example
```json
{
  "type": "open_orders",
  "orders": [
    {"order_id": 5531, "symbol": "AAPL", "side": "buy", "price": 180.0, "orig_qty": 10.0, "remaining_qty": 10.0},
    {"order_id": 5540, "symbol": "BTC", "side": "sell", "price": 51000.0, "orig_qty": 0.05, "remaining_qty": 0.02}
  ]
}
```

### Client → Server Messages

#### `place_order`
```json
{"type":"place_order", "symbol":"AAPL", "order_type":"limit", "side":"buy", "price":180.0, "qty":10.0}
```
| Field | Required | Notes |
|-------|----------|-------|
| `symbol` | ✅ | Must match an active symbol |
| `order_type` | ✅ | `"limit"` or `"market"` |
| `side` | ✅ | `"buy"` or `"sell"` |
| `price` | For limit | Ignored for market orders |
| `qty` | ✅ | Must be positive |

#### `cancel_order`
```json
{"type":"cancel_order", "symbol":"AAPL", "order_id":5531}
```

#### `get_symbols`
```json
{"type":"get_symbols"}
```

#### `ping`
```json
{"type":"ping"}
```

### Rate Limiting
All messages except `ping` consume one token from a per-connection bucket (50 tokens max, refills at 50/sec). If exceeded:
```json
{"type": "error", "message": "Rate limit exceeded (max 50 msgs/sec)"}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    main.cpp (uWebSocket)                │
│  ┌──────────┐  ┌────────────┐  ┌───────────────────┐   │
│  │ WS Event │  │ Broadcaster│  │ Sector Factor     │   │
│  │ Loop     │  │ Thread     │  │ Thread (20ms)     │   │
│  │ (Thread1)│  │ (100ms)    │  │ tech/fin/crypto   │   │
│  └────┬─────┘  └─────┬──────┘  └───────────────────┘   │
│       │              │                                  │
│  ┌────▼──────────────▼──────────────────────────────┐   │
│  │            Exchange (per-symbol)                  │   │
│  │  ┌──────────────────────────────────────────────┐ │   │
│  │  │ SymbolState (×10)                            │ │   │
│  │  │  MatchingEngine ← OrderBook (RB-Tree)        │ │   │
│  │  │  MarketSimulator (Heston+Jump+SmartMM thread)│ │   │
│  │  │  CandleAggregator (1s OHLCV)                 │ │   │
│  │  └──────────────────────────────────────────────┘ │   │
│  └───────────────────────────────────────────────────┘   │
│                                                         │
│  Per-connection: TokenBucket rate limiter                │
│  Global: g_open_orders, g_portfolios (mutex-guarded)    │
└─────────────────────────────────────────────────────────┘
```

---

## Key Design Notes

- Every connection gets a **unique `user_id`** and **$100,000 starting capital**
- **Short selling** is fully supported
- Portfolio and open orders are maintained **server-side** — no client-side state needed
- **Sector correlation**: Tech, Financial, and Crypto factors are drawn independently each tick. Sector factors are stored as `std::atomic<double>` per sector, written by the factor thread and read lock-free by each symbol's simulator thread, completely eliminating data races without mutex overhead. JPM does not correlate with BTC.
- **Inventory limit toggle**: Set `use_inventory_limit = false` in `SymbolConfig` to allow the bot to quote both sides unconditionally, regardless of its net position. Useful for stress-testing liquidity.
- Inventory tracking uses **`std::atomic<double>`** updated after `processOrder()` returns (not inside the trade callback) to prevent deadlocks
- Volume clustering evolves **log(activity)** for numerical stability
- The Heston variance floor uses **`abs(v) ≥ 1e-6`** (reflection scheme) to prevent price freezing near zero
- **dt_ calibration**: `dt_ = 0.00008` gives ≈1 trading-second per 20ms tick, compressing one full trading day into ~6.5 minutes of real time. This guarantees prices remain stable over hours of continuous operation.