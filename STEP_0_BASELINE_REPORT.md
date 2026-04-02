# Step 0 Baseline Report - Scheduled and Replay Sessions Initiative

## Metadata

1. Date: 2026-04-02
2. Environment: Docker (engine + admin_api) with local validation clients
3. Reviewer: GitHub Copilot (GPT-5.3-Codex)

---

## Baseline Checks (Must Pass Before Step 1)

1. Engine websocket reachable and bot auth works.
2. Worker connects with admin key and receives trade firehose.
3. Admin API routes used by frontend are healthy.
4. Bot Compare lap Start/Stop and polling behave as expected.
5. No regression seen in existing manual bot workflows.

---

## Execution Log

## Check 1: Engine websocket and bot auth

Status: PASS

Evidence:

1. Engine port check at 2026-04-02T20:14:13+05:30 returned `ENGINE_TCP:True` for `127.0.0.1:9001`.
2. Auth probe succeeded (`AUTH_MATCH:True`) for bot `4afdd95a-c6cb-46c5-b9c4-29a06adddda3`.

## Check 2: Worker firehose and DB commits

Status: PASS

Evidence:

1. Admin container log shows worker admin auth success: `{"role":"admin","type":"auth_success"}`.
2. Worker committed trade batches for bot `4afdd95a-c6cb-46c5-b9c4-29a06adddda3` (multiple `Committing batch of ... trades` entries).

## Check 3: Admin API route health

Status: PASS

Evidence:

1. `POST /api/bots` succeeded and returned bot id `94d1fbe9-17bb-4d4c-985d-7fdc4265880b`.
2. `GET /api/bots`, `GET /portfolio`, `GET /kpi`, and session routes all returned HTTP 200.

## Check 4: Bot Compare lap controls

Status: PASS

Evidence:

1. Backing lap endpoints succeeded: `POST /sessions/start` returned `active`; `POST /sessions/stop` returned `completed`.
2. `GET /sessions` returned expected session history (`SESSIONS_COUNT:1`) for the test bot.

## Check 5: Manual workflow regression scan

Status: PASS

Evidence:

1. Manual authenticated trade path validated: websocket auth + market order flow produced persisted trades (`API_TRADE_COUNT:30`).
2. Manual order management validated: authenticated limit order received `ack` (`FLOW_ORDER_ID:170226`) and successful `cancel_ack` (`FLOW_CANCEL_OK:True`).

---

## Step 0 Decision

1. Ready for Step 1: YES
2. Blocking issues:
3. None for Step 1 start (Docker baseline validated).
4. Optional: local C++ toolchain setup remains pending if non-Docker local engine runs are needed.

Approval:

1. Name: Ready for user sign-off
2. Date: 2026-04-02
