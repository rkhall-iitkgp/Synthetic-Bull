# Trading Backend Stepwise Fix Plan

## 1) Deployment Trust Model (Confirmed)

- Frontend connects as one shared guest identity: `frontend_user`.
- Shared frontend guest is treated as admin in this environment.
- Bots authenticate using API keys from DB.
- This is a controlled simulation/training environment, not a public exchange.

## 2) Current Status

- [x] Step 1: Enforce frontend guest admin role in websocket session flags.
- [x] Step 2: Guard admin-only deposit route and harden cancel ownership flow.
- [x] Step 3: Prevent buy-side overcommit by reserving cash for resting buy limits.
- [x] Step 4: Replace market-buy risk estimate with orderbook walk worst-case pricing.
- [ ] Step 5: Improve order id safety across symbols and owner checks at engine boundary.
- [ ] Step 6: Add bounded queues and backpressure to broadcast/trade pipelines.
- [ ] Step 7: Move market feed from periodic full snapshots to delta-first updates.
- [ ] Step 8: Optimize matching core data structures for extreme performance.

## 3) Completed Changes

### Step 1 (Completed)

- File: `backend/src/main.cpp`
- Change: `guest_login` now sets `is_admin = true` for the shared frontend session.
- Reason: Matches the agreed trust model where frontend guest acts as admin.

### Step 2 (Completed)

- File: `backend/src/main.cpp`
- Change A: `deposit` now requires `data->is_admin`.
- Change B: `cancel_order` validates user ownership for non-admin sessions before cancel.
- Change C: open-order cleanup on cancel now matches both `order_id` and `symbol`.
- Reason: Prevent unauthorized balance changes and reduce order bookkeeping mismatch.

### Step 3 (Completed)

- File: `backend/src/main.cpp`
- Change A: Added `reservedBuyNotional(uid)` helper from resting open buy orders.
- Change B: BUY risk check now validates `cash >= reserved_buy_notional + new_order_cost`.
- Reason: Prevent stacked resting buy limits from overcommitting available cash.

### Step 4 (Completed)

- File: `backend/src/main.cpp`
- Change A: Added `estimateMarketBuyCost(...)` using live ask levels from `engine->getSnapshot(200)`.
- Change B: Market BUY now requires sufficient book liquidity and uses depth-walk cost for cash precheck.
- Reason: Prevent acceptance of market buys that cannot be funded at executable prices.

## 4) Next Fixes (Execution Order)

### Step 5: Stronger identity and id safety

Goal:
- Remove residual ambiguity from per-symbol order id spaces.

Implementation:
- Preferred: move to exchange-global order ids.
- Interim: keep symbol-bound checks everywhere and add owner-aware cancel API.

Acceptance:
- No cross-symbol or cross-user cancel ambiguity.

### Step 6: Bounded queues and backpressure

Goal:
- Avoid unbounded memory growth under spikes.

Implementation:
- Bound trade queue size with policy (drop oldest or coalesce).
- Track queue depth and emit warnings/metrics.

Acceptance:
- Memory remains bounded under stress.

### Step 7: Delta-first market data

Goal:
- Reduce serialization and publish overhead.

Implementation:
- Push incremental updates for affected symbols.
- Keep periodic snapshots only for recovery/resync.

Acceptance:
- Lower CPU usage and lower publish latency at same load.

### Step 8: Matching core performance rewrite

Goal:
- Reach extreme performance with low p99 latency.

Implementation:
- Integer ticks/lots.
- Faster cancel index (O(1)-style by id to node handle).
- Memory pooling for orders/trades.
- Build flags: O3 + LTO + CPU-tuned release profile.

Acceptance:
- Lower p50/p99 latency and higher sustained throughput in load tests.

## 5) Suggested Validation Checklist Per Step

- Unit tests for new invariants.
- Load test before and after step.
- Compare p50/p95/p99 latency and throughput.
- Check portfolio/open-order consistency after cancel and fills.
- Confirm short-selling guardrails still pass all scenarios.
