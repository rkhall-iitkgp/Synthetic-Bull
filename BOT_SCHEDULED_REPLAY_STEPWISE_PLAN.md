# Synthetic-Bull Bot Scheduled + Replay Sessions Stepwise Plan

## 1) Objective

Add two capabilities on top of the current system without breaking existing behavior:

1. Scheduled live bot sessions (future time windows).
2. Historical replay sessions (bots trade on past generated market data).

This plan is additive and keeps current bot auth, trading, worker logging, and dashboard features intact.

---

## Execution Progress

1. Step 0: Completed (2026-04-02)
2. Step 1: Completed (2026-04-02)
3. Step 2: Completed (2026-04-02)
4. Step 3: Completed (2026-04-02)
5. Step 4: Completed (2026-04-02)
6. Step 5: Completed (2026-04-02)
7. Step 6: Completed (2026-04-02)
8. Step 7: Completed (2026-04-02)
9. Step 8: Completed (2026-04-02)
10. Step 9: Completed (2026-04-02)

---

## 2) Existing Structure to Reuse (No Rewrite)

1. C++ matching engine websocket protocol and auth flow.
2. Admin API session/trade/portfolio data model and worker pipeline.
3. Bot runtime contract (`BOT_API_KEY`, `EXCHANGE_WS_URL`) and `ExchangeClient` behavior.
4. Frontend bot compare and lap controls already using session concepts.

---

## 3) Compatibility Rules (Must Hold in Every Step)

1. No breaking websocket message schema for existing bot clients.
2. No change to current manual bot execution path unless feature flag is enabled.
3. Existing `BotPanel` start/stop flow must continue to work unchanged.
4. Worker trade logging must keep current semantics for non-scheduled flows.
5. New schema changes must be additive (new tables/columns, no destructive rename/drop).

---

## 4) Feature Flags (Safety Switches)

Introduce and default to disabled:

1. `ENABLE_SESSION_ORCHESTRATOR=0`
2. `ENABLE_SCHEDULED_LIVE_SESSIONS=0`
3. `ENABLE_REPLAY_SESSIONS=0`

Rollout rule:

1. Enable one flag at a time only after smoke checks pass.

---

## 5) Step-by-Step Execution Plan

## Step 0: Baseline and Regression Guardrail

Goal:

1. Freeze baseline behavior before adding new features.

Tasks:

1. Capture current smoke checklist:
2. Bot auth and order placement.
3. Worker receives firehose trades and commits to DB.
4. Bot compare lap start/stop and live polling.
5. Snapshot current API routes used by frontend and bots.

Acceptance:

1. All current smoke checks pass exactly as today.

---

## Step 1: Session Domain Model (Additive Schema)

Goal:

1. Introduce run scheduling entities without touching current runtime flow.

New entities:

1. `session_templates` (what to run, when, recurrence, mode).
2. `session_runs` (one concrete execution instance with state).
3. `session_run_bots` (bot assignments per run).
4. `market_datasets` (historical dataset metadata for replay mode).
5. `session_run_events` (audit trail for run transitions/errors).

Run states:

1. `scheduled`
2. `starting`
3. `running`
4. `stopping`
5. `completed`
6. `failed`
7. `cancelled`

Acceptance:

1. Migrations succeed.
2. Existing API and worker behavior remains unchanged.

---

## Step 2: Admin API for Templates and Runs (Control Plane Only)

Goal:

1. Expose run planning APIs without launching bots yet.

Tasks:

1. Create CRUD endpoints for `session_templates`.
2. Add endpoint to create a `session_run` from a template.
3. Add list/detail endpoints for runs and run events.
4. Add validation for mode-specific fields:
5. Live mode requires schedule window.
6. Replay mode requires dataset id and replay speed.

Acceptance:

1. Frontend/admin can create and inspect runs.
2. No runtime side effects yet (no bot start/stop).

---

## Step 3: Scheduler Loop (State Transitions Only)

Goal:

1. Add scheduler that moves due runs into lifecycle states safely.

Tasks:

1. Background scheduler polls due `scheduled` runs.
2. Use idempotency lock so one run starts once.
3. Record every transition in `session_run_events`.
4. Add retry policy for transient failures with max attempts.

Acceptance:

1. Run transitions are deterministic and auditable.
2. Existing bot/manual flows unchanged with flags disabled.

---

## Step 4: Scheduled Live Session Execution

Goal:

1. Start/stop bots automatically for live scheduled runs.

Tasks:

1. On run start:
2. Launch assigned bots with current auth flow and engine URL.
3. Record launch metadata and heartbeat.
4. On run stop:
5. Stop bot processes cleanly.
6. Optional cancel-all safety action per bot.
7. Link run to existing lap/session concept for KPI grouping.

Acceptance:

1. Scheduled run starts bots at planned time.
2. Scheduled stop finalizes run and preserves current manual controls.

---

## Step 5: KPI and Trade Attribution by Run

Goal:

1. Allow per-run analytics while preserving existing totals.

Tasks:

1. Add nullable run attribution (`run_id`) to relevant records or association tables.
2. Update worker attribution path so trades during a run map to that run.
3. Keep legacy queries defaulting to all-time behavior if no run filter is passed.

Acceptance:

1. Existing dashboard metrics remain valid without run filters.
2. New run-filtered metrics match run windows.

---

## Step 6: Historical Replay Data Pipeline

Goal:

1. Prepare and register historical generated market data for replay runs.

Tasks:

1. Define replay dataset format (timestamped orderbook/candle/trade events).
2. Build dataset registry entries in `market_datasets`.
3. Add integrity checks (time ordering, symbol consistency, schema version).

Acceptance:

1. Replay datasets are discoverable and validated before run start.

---

## Step 7: Replay Execution Engine Adapter

Goal:

1. Execute bots on past data using the same client protocol.

Tasks:

1. Create replay websocket source that mimics current engine event contracts.
2. Support virtual time speed controls (1x/5x/20x).
3. Route replay bots via `EXCHANGE_WS_URL` to replay endpoint.
4. Keep replay isolated from live execution state.

Acceptance:

1. Bots run unchanged against replay endpoint.
2. Replay can be repeated with identical dataset and config.

---

## Step 8: Frontend Rollout (Incremental)

Goal:

1. Add schedule/replay control UI while preserving current panels.

Tasks:

1. Add a scheduler view for template and run management.
2. Add run monitor panel with state timeline and errors.
3. Add replay launcher with dataset and speed selector.
4. Keep current `BotPanel` controls as fallback/manual mode.

Acceptance:

1. Existing dashboard workflows continue to function.
2. New pages are gated behind feature flags until validated.

---

## Step 9: Hardening and Rollout

Goal:

1. Ensure reliability before default enablement.

Tasks:

1. Timezone and DST tests for scheduler boundaries.
2. Restart recovery tests (admin API, worker, replay source).
3. Run cancellation and kill-switch tests.
4. Backpressure and queue behavior under load.

Acceptance:

1. Zero regression in existing features.
2. New flows pass failure drills and smoke checks.

---

## 6) Suggested Execution Order for You (One by One)

1. Execute Step 0 and Step 1 first.
2. Do not move to Step 2 until Step 1 acceptance passes.
3. Keep each step in an isolated commit.
4. Run smoke checklist after every step.

---

## 7) Definition of Done

1. Scheduled live runs can start/stop bots by plan.
2. Replay runs execute bots on historical datasets without code changes to bot strategies.
3. Trade/KPI views can be filtered by run.
4. Existing manual bot controls and current dashboard features remain operational.

---

## 8) Immediate Next Action (Step 0 Execution Checklist)

Use this before any schema or runtime change:

1. Verify engine websocket is reachable and bot auth still works.
2. Verify worker connects with admin key and receives trades.
3. Verify admin API serves current bot/session/kpi endpoints used by frontend.
4. Verify Bot Compare lap Start/Stop and polling still behave correctly.
5. Save a baseline note with pass/fail and timestamp for each check.

Step 0 sign-off rule:

1. Do not start Step 1 unless all 5 checks pass.
