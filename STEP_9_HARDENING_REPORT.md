# Step 9 Hardening Report - Scheduled Live and Replay Sessions

## Metadata

1. Date: 2026-04-02
2. Environment: Docker compose (`engine` + `admin_api`) with orchestrator and replay flags enabled
3. Reviewer: GitHub Copilot (GPT-5.3-Codex)

---

## Scope

1. Validate end-to-end scheduled live run execution.
2. Validate end-to-end replay run execution from NDJSON dataset.
3. Validate run-scoped attribution (`run_id`) for trades and sessions.
4. Validate mode-specific API guardrails.

---

## Runtime Preconditions

1. Orchestrator flags enabled for validation run:
2. `ENABLE_SESSION_ORCHESTRATOR=1`
3. `ENABLE_SCHEDULED_LIVE_SESSIONS=1`
4. `ENABLE_REPLAY_SESSIONS=1`
5. Replay dataset file generated at `/data/replay_step9.ndjson` with 240 events.

---

## Validation Results

## A) Health and Scheduler

Status: PASS

Evidence:

1. `GET /api/system/health/session-orchestrator` returned:
2. `orchestrator_enabled=true`
3. `scheduled_live_enabled=true`
4. `replay_enabled=true`
5. `db_quick_check="ok"`

## B) Replay End-to-End Run

Status: PASS

Evidence:

1. Replay dataset validation:
2. `POST /api/market-datasets/{id}/validate` -> `ok=true`, `event_count=240`.
3. Replay run lifecycle observed:
4. `scheduled -> starting -> running -> stopping -> completed`.
5. Replay assignment status reached `completed`.
6. Run-scoped trade attribution produced persisted trades:
7. `GET /api/bots/{bot_id}/trades?run_id={replay_run_id}` returned `5` trades.

## C) Scheduled Live End-to-End Run

Status: PASS

Evidence:

1. Live run reached `running` state from scheduler.
2. Manual operator cancel path succeeded:
3. `POST /api/session-runs/{run_id}/cancel` -> `status=cancelled`.
4. Live run-scoped attribution persisted:
5. `GET /api/bots/{bot_id}/trades?run_id={live_run_id}` returned `2` trades.
6. `GET /api/bots/{bot_id}/sessions?run_id={live_run_id}` returned `1` session.

## D) API Validation Guardrails

Status: PASS

Evidence:

1. Invalid live schedule rejected:
2. `POST /api/session-templates` with end before start -> HTTP `400`.
3. Error detail: `schedule_end_time must be after schedule_start_time.`

---

## Additional Hardening Fixes Applied During Validation

1. `backend/admin_api/bot_runtime.py`
2. Added robust bot working-directory resolution with explicit fallback guidance.
3. Added cleanup for empty process maps on bot launch failure.
4. `docker-compose.yml`
5. Mounted host bots folder into admin container (`./bots:/bots`).
6. Added `BOT_WORKING_DIR=/bots` environment variable for deterministic runtime pathing.

---

## Step 9 Decision

1. Step 9 hardening checklist: COMPLETE
2. Blocking issues: None identified in this validation pass.
3. Residual observation:
4. `GET /api/session-runs/{run_id}/replay/control` returns `status="missing"` after replay completion because run state is cleaned up after stop. This is acceptable for current implementation and reflects completed teardown.
