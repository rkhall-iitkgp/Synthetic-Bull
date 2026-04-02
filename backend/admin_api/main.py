import uuid
import secrets
import asyncio
import os
import json
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
import datetime
from sqlalchemy import text

import models, schemas
from database import engine, get_db, SessionLocal
from sqlalchemy.sql import func
from worker import logger_worker, deposit_queue, process_trade_fifo, update_market_price
from bot_runtime import LiveBotProcessRegistry, infer_strategy_module
from replay_runtime import (
    ReplayClient,
    ReplayManager,
    apply_fill,
    build_portfolio_payload,
    choose_exec_price,
    order_to_trade_payload,
    register_replay_websocket,
    unregister_replay_websocket,
    validate_replay_dataset,
)

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Synthetic Bull - Admin API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: List[WebSocket] = []

ENABLE_SESSION_ORCHESTRATOR = os.getenv("ENABLE_SESSION_ORCHESTRATOR", "0") == "1"
ENABLE_SCHEDULED_LIVE_SESSIONS = os.getenv("ENABLE_SCHEDULED_LIVE_SESSIONS", "0") == "1"
ENABLE_REPLAY_SESSIONS = os.getenv("ENABLE_REPLAY_SESSIONS", "0") == "1"
SCHEDULER_POLL_SECONDS = float(os.getenv("SCHEDULER_POLL_SECONDS", "2"))
SCHEDULER_MAX_RETRIES = int(os.getenv("SCHEDULER_MAX_RETRIES", "3"))
SCHEDULED_CANCEL_ALL_ON_STOP = os.getenv("SCHEDULED_CANCEL_ALL_ON_STOP", "0") == "1"

LIVE_EXCHANGE_WS_URL = os.getenv("LIVE_EXCHANGE_WS_URL", os.getenv("ENGINE_WS_URL", "ws://127.0.0.1:9001"))
REPLAY_PUBLIC_WS_BASE = os.getenv("REPLAY_PUBLIC_WS_BASE", "ws://127.0.0.1:8000")
REPLAY_DATASETS_DIR = Path(os.getenv("REPLAY_DATASETS_DIR", str(Path(os.getenv("DB_DIR", "./")) / "replay_datasets")))

_scheduler_lock = asyncio.Lock()
_run_retry_counts: Dict[str, int] = {}

_bot_registry = LiveBotProcessRegistry()
_replay_manager = ReplayManager()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_column(conn, table_name: str, column_name: str, declaration: str):
    if not _column_exists(conn, table_name, column_name):
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {declaration}"))


def ensure_additive_schema():
    # create_all creates missing tables but does not add missing columns in existing tables.
    with engine.begin() as conn:
        _ensure_column(conn, "bots", "strategy_module", "VARCHAR DEFAULT 'alpha.main'")
        _ensure_column(conn, "session_templates", "launch_config_json", "TEXT")
        _ensure_column(conn, "market_datasets", "format_type", "VARCHAR DEFAULT 'ndjson_v1'")
        _ensure_column(conn, "market_datasets", "validation_error", "TEXT")
        _ensure_column(conn, "market_datasets", "last_validated_at", "DATETIME")
        _ensure_column(conn, "session_runs", "replay_endpoint", "VARCHAR")
        _ensure_column(conn, "session_run_bots", "strategy_module", "VARCHAR")
        _ensure_column(conn, "session_run_bots", "pid", "INTEGER")
        _ensure_column(conn, "bot_sessions", "run_id", "VARCHAR")
        _ensure_column(conn, "trades", "run_id", "VARCHAR")
        _ensure_column(conn, "trade_rounds", "run_id", "VARCHAR")


def _create_state_event(
    db: Session,
    run_id: str,
    from_state: Optional[str],
    to_state: str,
    message: str,
):
    db.add(
        models.SessionRunEvent(
            run_id=run_id,
            event_type="state_transition",
            from_state=from_state,
            to_state=to_state,
            message=message,
            payload_json=None,
        )
    )


def _create_error_event(db: Session, run_id: str, current_state: str, message: str):
    db.add(
        models.SessionRunEvent(
            run_id=run_id,
            event_type="error",
            from_state=current_state,
            to_state=current_state,
            message=message,
            payload_json=None,
        )
    )


def _as_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _parse_launch_config(template: models.SessionTemplate) -> Dict[str, Any]:
    if not template.launch_config_json:
        return {}
    try:
        parsed = json.loads(template.launch_config_json)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _resolve_strategy_module(template: models.SessionTemplate, bot: models.Bot) -> str:
    launch_cfg = _parse_launch_config(template)
    default_module = launch_cfg.get("default_module") if isinstance(launch_cfg, dict) else None
    bot_modules = launch_cfg.get("bot_modules", {}) if isinstance(launch_cfg, dict) else {}
    by_bot_module = bot_modules.get(bot.id) if isinstance(bot_modules, dict) else None

    explicit = by_bot_module or default_module or bot.strategy_module
    return infer_strategy_module(bot.name, explicit)


def _resolve_template_primary_symbol(template: Optional[models.SessionTemplate]) -> Optional[str]:
    if not template or not template.symbols_json:
        return None
    try:
        parsed = json.loads(template.symbols_json)
        if isinstance(parsed, list) and parsed:
            return str(parsed[0]).upper()
        if isinstance(parsed, str) and parsed:
            return parsed.upper()
    except Exception:
        return None
    return None


def _build_bot_env_overrides(template: Optional[models.SessionTemplate]) -> Dict[str, str]:
    symbol = _resolve_template_primary_symbol(template)
    if not symbol:
        return {}
    return {
        "ALPHA_SYMBOL": symbol,
        "MM_SYMBOL": symbol,
    }


def _normalize_candle_ts_us(raw_ts: float) -> int:
    ts = float(raw_ts)
    if ts <= 0:
        raise ValueError("candle time must be positive")
    # seconds -> microseconds
    if ts < 1e11:
        return int(ts * 1_000_000)
    # milliseconds -> microseconds
    if ts < 1e14:
        return int(ts * 1_000)
    # already microseconds
    return int(ts)


def _write_replay_dataset_from_candles(
    dataset_path: Path,
    symbol: str,
    candles: List[schemas.ReplayCandleInput],
    start_index: int,
    end_index: int,
) -> int:
    if not candles:
        raise HTTPException(status_code=400, detail="candles must not be empty")

    max_index = len(candles) - 1
    start = max(0, min(start_index, max_index))
    end = max(start, min(end_index, max_index))
    selected = candles[start : end + 1]
    if len(selected) < 2:
        raise HTTPException(status_code=400, detail="Replay range must contain at least 2 candles")

    dataset_path.parent.mkdir(parents=True, exist_ok=True)

    previous_ts = -1
    with dataset_path.open("w", encoding="utf-8") as fh:
        for candle in selected:
            try:
                ts_us = _normalize_candle_ts_us(candle.time)
            except Exception as ts_error:
                raise HTTPException(status_code=400, detail=f"Invalid candle time: {ts_error}") from ts_error

            if ts_us <= previous_ts:
                ts_us = previous_ts + 1
            previous_ts = ts_us

            o = float(candle.open)
            h = float(candle.high)
            l = float(candle.low)
            c = float(candle.close)
            v = max(float(candle.volume or 0.0), 0.0)

            spread = max(0.01, abs(h - l) * 0.02)
            bid = round(c - spread / 2.0, 6)
            ask = round(c + spread / 2.0, 6)

            orderbook_event = {
                "type": "orderbook",
                "symbol": symbol,
                "ts": ts_us,
                "mid": round(c, 6),
                "spread": round(spread, 6),
                "bids": [[bid, max(v, 1.0), 1]],
                "asks": [[ask, max(v, 1.0), 1]],
            }
            candle_event = {
                "type": "candle",
                "symbol": symbol,
                "ts": ts_us,
                "t": int(ts_us / 1000),
                "o": round(o, 6),
                "h": round(h, 6),
                "l": round(l, 6),
                "c": round(c, 6),
                "v": round(v, 6),
            }

            fh.write(json.dumps(orderbook_event, separators=(",", ":")) + "\n")
            fh.write(json.dumps(candle_event, separators=(",", ":")) + "\n")

    return len(selected)


def _start_run_lap_session(db: Session, bot_id: str, run_id: str, now_utc: datetime.datetime):
    active_lap = db.query(models.BotSession).filter(
        models.BotSession.bot_id == bot_id,
        models.BotSession.session_type == "lap",
        models.BotSession.status == "active",
    ).first()

    if active_lap:
        if active_lap.run_id == run_id:
            return active_lap
        raise RuntimeError(f"Bot {bot_id} already has an active lap session outside run {run_id}")

    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    starting_equity = portfolio.initial_capital if portfolio else 0.0

    session = models.BotSession(
        bot_id=bot_id,
        run_id=run_id,
        session_type="lap",
        starting_equity=starting_equity,
        max_equity=starting_equity,
        min_equity=starting_equity,
        start_time=now_utc,
    )
    db.add(session)
    db.flush()
    return session


def _stop_run_lap_sessions(db: Session, run_id: str, now_utc: datetime.datetime):
    sessions = db.query(models.BotSession).filter(
        models.BotSession.run_id == run_id,
        models.BotSession.session_type == "lap",
        models.BotSession.status == "active",
    ).all()
    for session in sessions:
        session.status = "completed"
        session.end_time = now_utc


def _persist_replay_trade(
    bot_id: str,
    run_id: str,
    symbol: str,
    side: str,
    price: float,
    qty: float,
    ts_us: int,
):
    db = SessionLocal()
    try:
        trade = models.Trade(
            id=f"replay_{run_id}_{uuid.uuid4().hex[:12]}_{side}",
            bot_id=bot_id,
            run_id=run_id,
            symbol=symbol,
            side=side,
            price=price,
            qty=qty,
            unclosed_qty=qty,
            timestamp=datetime.datetime.fromtimestamp(ts_us / 1_000_000.0, tz=datetime.timezone.utc),
        )
        process_trade_fifo(db, trade)
        update_market_price(db, symbol, price)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Replay] Failed to persist trade: {e}")
    finally:
        db.close()


async def _start_live_run_execution(db: Session, run: models.SessionRun, now_utc: datetime.datetime):
    if not ENABLE_SCHEDULED_LIVE_SESSIONS:
        raise RuntimeError("ENABLE_SCHEDULED_LIVE_SESSIONS is disabled")

    assignments = list(run.assignments)
    if not assignments:
        raise RuntimeError("Run has no bot assignments")

    template = run.template
    env_overrides = _build_bot_env_overrides(template)
    started_count = 0

    for assignment in assignments:
        bot = db.query(models.Bot).filter(models.Bot.id == assignment.bot_id).first()
        if not bot:
            assignment.status = "failed"
            assignment.last_error = f"Bot {assignment.bot_id} not found"
            continue

        strategy_module = assignment.strategy_module or (
            _resolve_strategy_module(template, bot) if template else infer_strategy_module(bot.name, bot.strategy_module)
        )

        managed = _bot_registry.start_bot(
            run_id=run.id,
            bot_id=bot.id,
            bot_name=bot.name,
            api_key=bot.api_key,
            strategy_module=strategy_module,
            exchange_ws_url=LIVE_EXCHANGE_WS_URL,
            replay_mode=False,
            extra_env=env_overrides,
        )

        _start_run_lap_session(db, bot.id, run.id, now_utc)

        assignment.status = "running"
        assignment.strategy_module = strategy_module
        assignment.pid = managed.process.pid
        assignment.started_at = now_utc
        assignment.heartbeat_at = now_utc
        assignment.ended_at = None
        assignment.last_error = None
        assignment.launch_meta_json = json.dumps(
            {
                "mode": "live",
                "exchange_ws_url": LIVE_EXCHANGE_WS_URL,
                "strategy_module": strategy_module,
                "pid": managed.process.pid,
                "log_file_path": managed.log_file_path,
            }
        )
        started_count += 1

    if started_count == 0:
        raise RuntimeError("Failed to start any live bot process")

    old_status = run.status
    run.status = "running"
    run.actual_start_time = now_utc
    run.error_message = None
    _create_state_event(db, run.id, old_status, run.status, f"Started {started_count}/{len(assignments)} live bot(s)")


async def _start_replay_run_execution(db: Session, run: models.SessionRun, now_utc: datetime.datetime):
    if not ENABLE_REPLAY_SESSIONS:
        raise RuntimeError("ENABLE_REPLAY_SESSIONS is disabled")

    if not run.replay_dataset:
        raise RuntimeError("Replay run has no dataset attached")
    dataset = run.replay_dataset
    if not dataset.file_path:
        raise RuntimeError("Replay dataset does not have file_path configured")

    summary = validate_replay_dataset(dataset.file_path)
    dataset.last_validated_at = now_utc
    if not summary.ok:
        dataset.status = "invalid"
        dataset.validation_error = summary.error
        raise RuntimeError(summary.error or "Replay dataset validation failed")

    dataset.status = "ready"
    dataset.validation_error = None
    dataset.event_count = summary.event_count
    dataset.start_time = summary.start_time
    dataset.end_time = summary.end_time

    replay_state = await _replay_manager.create_or_replace_run(
        run_id=run.id,
        speed=run.replay_speed,
        dataset_path=dataset.file_path,
    )

    run.replay_endpoint = f"{REPLAY_PUBLIC_WS_BASE.rstrip('/')}/ws/replay/{run.id}"

    assignments = list(run.assignments)
    if not assignments:
        raise RuntimeError("Replay run has no bot assignments")

    template = run.template
    env_overrides = _build_bot_env_overrides(template)
    started_count = 0
    for assignment in assignments:
        bot = db.query(models.Bot).filter(models.Bot.id == assignment.bot_id).first()
        if not bot:
            assignment.status = "failed"
            assignment.last_error = f"Bot {assignment.bot_id} not found"
            continue

        strategy_module = assignment.strategy_module or (
            _resolve_strategy_module(template, bot) if template else infer_strategy_module(bot.name, bot.strategy_module)
        )
        managed = _bot_registry.start_bot(
            run_id=run.id,
            bot_id=bot.id,
            bot_name=bot.name,
            api_key=bot.api_key,
            strategy_module=strategy_module,
            exchange_ws_url=run.replay_endpoint,
            replay_mode=True,
            extra_env=env_overrides,
        )

        _start_run_lap_session(db, bot.id, run.id, now_utc)

        assignment.status = "running"
        assignment.strategy_module = strategy_module
        assignment.pid = managed.process.pid
        assignment.started_at = now_utc
        assignment.heartbeat_at = now_utc
        assignment.ended_at = None
        assignment.last_error = None
        assignment.launch_meta_json = json.dumps(
            {
                "mode": "replay",
                "exchange_ws_url": run.replay_endpoint,
                "strategy_module": strategy_module,
                "pid": managed.process.pid,
                "events_total": len(replay_state.events),
                "log_file_path": managed.log_file_path,
            }
        )
        started_count += 1

    if started_count == 0:
        raise RuntimeError("Failed to start any replay bot process")

    old_status = run.status
    run.status = "running"
    run.actual_start_time = now_utc
    run.error_message = None
    _create_state_event(db, run.id, old_status, run.status, f"Started {started_count}/{len(assignments)} replay bot(s)")


def _heartbeat_assignments(db: Session, run: models.SessionRun, now_utc: datetime.datetime):
    any_running = False
    for assignment in run.assignments:
        if assignment.status not in ("running", "pending"):
            continue

        managed = _bot_registry.get(run.id, assignment.bot_id)
        if not managed:
            if assignment.status == "running":
                assignment.status = "failed"
                assignment.ended_at = now_utc
                assignment.last_error = "Bot process handle missing"
                _create_error_event(db, run.id, run.status, f"Bot {assignment.bot_id} process handle missing")
            continue

        exit_code = managed.process.poll()
        if exit_code is None:
            any_running = True
            assignment.status = "running"
            assignment.heartbeat_at = now_utc
        else:
            assignment.status = "failed"
            assignment.ended_at = now_utc
            assignment.last_error = f"Process exited with code {exit_code}"
            _create_error_event(db, run.id, run.status, f"Bot {assignment.bot_id} exited with code {exit_code}")

    if run.mode == "replay":
        replay_control = _replay_manager.control_payload(run.id)
        if replay_control["ready"] and replay_control["status"] == "completed":
            # Replay stream has finished; move run to stopping and clean up.
            old_state = run.status
            run.status = "stopping"
            _create_state_event(db, run.id, old_state, run.status, "Replay stream completed")
            return

    if not any_running and run.status == "running":
        old_state = run.status
        run.status = "failed"
        run.error_message = "All assigned bot processes stopped unexpectedly"
        _create_state_event(db, run.id, old_state, run.status, "Run failed: no running assignments remaining")


async def _stop_run_execution(db: Session, run: models.SessionRun, now_utc: datetime.datetime):
    stopped_map = _bot_registry.stop_run(run.id)

    for assignment in run.assignments:
        if assignment.status != "failed":
            assignment.status = "completed"
        assignment.ended_at = now_utc
        assignment.heartbeat_at = now_utc
        assignment.pid = None
        if assignment.bot_id in stopped_map:
            assignment.last_error = None

    if run.mode == "replay":
        await _replay_manager.stop_run(run.id)

    _stop_run_lap_sessions(db, run.id, now_utc)

    old_state = run.status
    run.status = "completed"
    run.actual_end_time = now_utc
    _create_state_event(db, run.id, old_state, run.status, "Run stop completed")

    if SCHEDULED_CANCEL_ALL_ON_STOP:
        db.add(
            models.SessionRunEvent(
                run_id=run.id,
                event_type="info",
                from_state=run.status,
                to_state=run.status,
                message="SCHEDULED_CANCEL_ALL_ON_STOP is enabled; explicit cancel-all engine hook not configured",
                payload_json=None,
            )
        )


async def _scheduler_handle_run(db: Session, run: models.SessionRun, now_utc: datetime.datetime):
    run_start_utc = _as_utc(run.scheduled_start_time)
    run_end_utc = _as_utc(run.scheduled_end_time)

    if run.status == "scheduled":
        if run_start_utc and run_start_utc <= now_utc:
            old_state = run.status
            run.status = "starting"
            _create_state_event(db, run.id, old_state, run.status, "Scheduled start time reached")
        return

    if run.status == "starting":
        if run.mode == "live":
            await _start_live_run_execution(db, run, now_utc)
        elif run.mode == "replay":
            await _start_replay_run_execution(db, run, now_utc)
        else:
            raise RuntimeError(f"Unsupported run mode: {run.mode}")
        return

    if run.status == "running":
        _heartbeat_assignments(db, run, now_utc)
        if run.status == "running" and run_end_utc and run_end_utc <= now_utc:
            old_state = run.status
            run.status = "stopping"
            _create_state_event(db, run.id, old_state, run.status, "Scheduled end time reached")
        return

    if run.status == "stopping":
        await _stop_run_execution(db, run, now_utc)
        return


async def session_scheduler_loop():
    while True:
        async with _scheduler_lock:
            db = SessionLocal()
            try:
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                runs = db.query(models.SessionRun).filter(
                    models.SessionRun.status.in_(["scheduled", "starting", "running", "stopping"])
                ).all()

                for run in runs:
                    try:
                        await _scheduler_handle_run(db, run, now_utc)
                        if run.id in _run_retry_counts and run.status not in ("starting", "stopping"):
                            _run_retry_counts.pop(run.id, None)
                    except Exception as transition_error:
                        retry_count = _run_retry_counts.get(run.id, 0) + 1
                        _run_retry_counts[run.id] = retry_count

                        _create_error_event(
                            db,
                            run.id,
                            run.status,
                            f"Scheduler transition failed (attempt {retry_count}): {transition_error}",
                        )

                        if retry_count >= SCHEDULER_MAX_RETRIES:
                            old_state = run.status
                            run.status = "failed"
                            run.error_message = f"Scheduler failed after {retry_count} attempts"
                            _create_state_event(db, run.id, old_state, run.status, "Scheduler moved run to failed")

                db.commit()
            except Exception as loop_error:
                db.rollback()
                print(f"[Scheduler] Loop error: {loop_error}")
            finally:
                db.close()

        await asyncio.sleep(SCHEDULER_POLL_SECONDS)


def _validate_schedule_window(start_time: Optional[datetime.datetime], end_time: Optional[datetime.datetime]):
    if not start_time or not end_time:
        raise HTTPException(status_code=400, detail="Live mode requires schedule_start_time and schedule_end_time.")
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="schedule_end_time must be after schedule_start_time.")


def _validate_mode_fields(
    db: Session,
    mode: str,
    schedule_start_time: Optional[datetime.datetime],
    schedule_end_time: Optional[datetime.datetime],
    replay_dataset_id: Optional[str],
    replay_speed: Optional[float],
):
    if mode not in ("live", "replay"):
        raise HTTPException(status_code=400, detail="mode must be either 'live' or 'replay'.")

    if mode == "live":
        _validate_schedule_window(schedule_start_time, schedule_end_time)
        if replay_dataset_id:
            raise HTTPException(status_code=400, detail="Live mode cannot include replay_dataset_id.")
        return

    if not replay_dataset_id:
        raise HTTPException(status_code=400, detail="Replay mode requires replay_dataset_id.")
    if replay_speed is None or replay_speed <= 0:
        raise HTTPException(status_code=400, detail="Replay mode requires replay_speed > 0.")

    dataset = db.query(models.MarketDataset).filter(models.MarketDataset.id == replay_dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Replay dataset not found.")
    if dataset.status == "invalid":
        raise HTTPException(status_code=400, detail="Replay dataset is invalid. Validate/fix dataset first.")

@app.on_event("startup")
async def startup_event():
    ensure_additive_schema()
    asyncio.create_task(logger_worker())
    print(
        "[Scheduler] Flags: "
        f"orchestrator={int(ENABLE_SESSION_ORCHESTRATOR)} "
        f"live={int(ENABLE_SCHEDULED_LIVE_SESSIONS)} "
        f"replay={int(ENABLE_REPLAY_SESSIONS)}"
    )
    if ENABLE_SESSION_ORCHESTRATOR:
        print("[Scheduler] ENABLE_SESSION_ORCHESTRATOR=1, starting scheduler loop")
        asyncio.create_task(session_scheduler_loop())
    else:
        print("[Scheduler] ENABLE_SESSION_ORCHESTRATOR=0, scheduler is disabled")

def generate_api_key():
    return f"sk_live_{secrets.token_hex(16)}"

@app.websocket("/ws/{bot_id}")
async def websocket_bot_endpoint(websocket: WebSocket, bot_id: str, db: Session = Depends(get_db)):
    await websocket.accept()
    
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        await websocket.close()
        return

    # Calculate starting equity
    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    starting_equity = portfolio.initial_capital if portfolio else 0.0

    # Start connection session
    session = models.BotSession(
        bot_id=bot_id,
        session_type="connection",
        starting_equity=starting_equity,
        max_equity=starting_equity,
        min_equity=starting_equity
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        session.status = "completed"
        session.end_time = func.now()
        db.commit()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)


@app.websocket("/ws/replay/{run_id}")
async def websocket_replay_endpoint(websocket: WebSocket, run_id: str):
    await websocket.accept()
    register_replay_websocket(websocket)

    run_state = _replay_manager.get_run(run_id)
    if not run_state:
        await websocket.send_json({"type": "error", "message": f"Replay run {run_id} is not available"})
        await websocket.close()
        unregister_replay_websocket(websocket)
        return

    db = SessionLocal()
    client: Optional[ReplayClient] = None

    try:
        try:
            raw_auth = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "error", "message": "Authentication timeout"})
            await websocket.close()
            return

        try:
            auth_msg = json.loads(raw_auth)
        except Exception:
            await websocket.send_json({"type": "error", "message": "Invalid auth payload"})
            await websocket.close()
            return

        if auth_msg.get("type") != "auth":
            await websocket.send_json({"type": "error", "message": "First message must be auth"})
            await websocket.close()
            return

        api_key = str(auth_msg.get("api_key", ""))
        bot = db.query(models.Bot).filter(models.Bot.api_key == api_key).first()
        if not bot:
            await websocket.send_json({"type": "error", "message": "Invalid API key"})
            await websocket.close()
            return

        portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot.id).first()
        initial_cash = float(portfolio.initial_capital if portfolio and portfolio.initial_capital else 100000.0)

        client = ReplayClient(bot_id=bot.id, user_id=bot.id, cash=initial_cash)
        run_state.add_client(id(websocket), client)

        symbols_payload = [
            {"symbol": symbol, "price": run_state.current_mid(symbol)}
            for symbol in sorted(run_state.symbols)
        ]
        await websocket.send_json({"type": "welcome", "user_id": bot.id, "symbols": symbols_payload})

        for symbol in sorted(run_state.symbols):
            await websocket.send_json(
                {
                    "type": "orderbook",
                    "symbol": symbol,
                    "mid": run_state.current_mid(symbol),
                    "spread": 0.0,
                    "bids": [],
                    "asks": [],
                    "ts": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000),
                }
            )

        await websocket.send_json(build_portfolio_payload(client, run_state.latest_mid_by_symbol))
        await websocket.send_json({"type": "open_orders", "orders": []})

        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload"})
                continue

            msg_type = payload.get("type")
            if msg_type == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "ts": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000),
                    }
                )
                continue

            if msg_type == "get_symbols":
                await websocket.send_json({"type": "symbols", "symbols": symbols_payload})
                continue

            if msg_type == "cancel_order":
                await websocket.send_json(
                    {
                        "type": "cancel_ack",
                        "symbol": payload.get("symbol", ""),
                        "order_id": int(payload.get("order_id", 0)),
                        "success": True,
                    }
                )
                continue

            if msg_type != "place_order":
                await websocket.send_json({"type": "error", "message": f"Unsupported message type: {msg_type}"})
                continue

            symbol = str(payload.get("symbol", ""))
            side = str(payload.get("side", "")).lower()
            qty = float(payload.get("qty", 0.0))
            if symbol not in run_state.symbols:
                await websocket.send_json({"type": "error", "message": f"Unknown symbol: {symbol}"})
                continue
            if side not in ("buy", "sell"):
                await websocket.send_json({"type": "error", "message": "side must be buy or sell"})
                continue
            if qty <= 0:
                await websocket.send_json({"type": "error", "message": "qty must be positive"})
                continue

            exec_price = choose_exec_price(run_state, symbol, payload)
            if exec_price <= 0:
                await websocket.send_json({"type": "error", "message": "Cannot determine executable replay price"})
                continue

            apply_fill(client, symbol, side, exec_price, qty)
            order_id = client.next_order_id
            client.next_order_id += 1

            await websocket.send_json(
                {
                    "type": "ack",
                    "symbol": symbol,
                    "order_id": order_id,
                    "status": "accepted",
                    "fills": 1,
                }
            )

            trade_payload = order_to_trade_payload(
                run_state=run_state,
                client=client,
                symbol=symbol,
                side=side,
                exec_price=exec_price,
                qty=qty,
            )
            await run_state.broadcast(trade_payload)
            await websocket.send_json(build_portfolio_payload(client, run_state.latest_mid_by_symbol))

            _persist_replay_trade(
                bot_id=client.bot_id,
                run_id=run_id,
                symbol=symbol,
                side=side,
                price=exec_price,
                qty=qty,
                ts_us=int(trade_payload["ts"]),
            )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[Replay] websocket handler error: {e}")
    finally:
        if client:
            run_state.remove_client(id(websocket))
        unregister_replay_websocket(websocket)
        db.close()

@app.post("/api/bots", response_model=schemas.BotResponse)
def create_bot(bot: schemas.BotCreate, db: Session = Depends(get_db)):
    api_key = generate_api_key()
    strategy_module = infer_strategy_module(bot.name, bot.strategy_module)
    
    db_bot = models.Bot(name=bot.name, api_key=api_key, strategy_module=strategy_module)
    db.add(db_bot)
    db.commit()
    db.refresh(db_bot)
    
    # Initialize portfolio
    db_portfolio = models.Portfolio(bot_id=db_bot.id, cash_balance=100000.0)
    db.add(db_portfolio)
    db.commit()
    
    return db_bot

@app.get("/api/bots", response_model=List[schemas.BotResponse])
def get_bots(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    bots = db.query(models.Bot).offset(skip).limit(limit).all()
    return bots

@app.get("/api/bots/{bot_id}", response_model=schemas.BotResponse)
def get_bot(bot_id: str, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot

@app.get("/api/bots/{bot_id}/trades", response_model=List[schemas.TradeResponse])
def get_bot_trades(
    bot_id: str,
    skip: int = 0,
    limit: int = 100,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    query = db.query(models.Trade).filter(models.Trade.bot_id == bot_id)
    if session_id:
        query = query.filter(models.Trade.session_id == session_id)
    if run_id:
        query = query.filter(models.Trade.run_id == run_id)

    trades = query.order_by(models.Trade.timestamp.desc()).offset(skip).limit(limit).all()
    return trades

@app.get("/api/bots/{bot_id}/portfolio")
def get_bot_portfolio(bot_id: str, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
        
    # Compute portfolio dynamically from trades
    trades = db.query(models.Trade).filter(models.Trade.bot_id == bot_id).all()

    portfolio_record = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    initial_capital = (portfolio_record.initial_capital if portfolio_record and portfolio_record.initial_capital else 100000.0)
    cash_balance = initial_capital
    positions = {}

    for t in trades:
        value = t.price * t.qty
        if t.side == "buy" or t.side == "BUY":
            cash_balance -= value
            positions[t.symbol] = positions.get(t.symbol, 0) + t.qty
        else:
            cash_balance += value
            positions[t.symbol] = positions.get(t.symbol, 0) - t.qty

    position_list = []
    for sym, qty in positions.items():
        if round(qty, 6) != 0:
            position_list.append({"symbol": sym, "qty": qty, "avg_entry_price": 0.0})

    return {
        "cash_balance": round(cash_balance, 2),
        "initial_capital": round(initial_capital, 2),
        "positions": position_list
    }

@app.get("/api/bots/{bot_id}/kpi", response_model=schemas.BotKPIResponse)
def get_bot_kpi(
    bot_id: str,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    import numpy as np

    if session_id:
        trade_rounds = db.query(models.TradeRound).filter(
            models.TradeRound.bot_id == bot_id,
            models.TradeRound.session_id == session_id
        ).all()
        session = db.query(models.BotSession).filter(
            models.BotSession.id == session_id,
            models.BotSession.bot_id == bot_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        max_eq = session.max_equity or 1.0
        min_eq = session.min_equity or 1.0
        drawdown = 0.0 if max_eq <= 0 else (max_eq - min_eq) / max_eq
    elif run_id:
        trade_rounds = db.query(models.TradeRound).filter(
            models.TradeRound.bot_id == bot_id,
            models.TradeRound.run_id == run_id,
        ).all()

        sessions = db.query(models.BotSession).filter(
            models.BotSession.bot_id == bot_id,
            models.BotSession.run_id == run_id,
        ).all()
        if not sessions:
            drawdown = 0.0
        else:
            max_eq = max((s.max_equity for s in sessions if s.max_equity), default=1.0)
            min_eq = min((s.min_equity for s in sessions if s.min_equity), default=1.0)
            drawdown = 0.0 if max_eq <= 0 else (max_eq - min_eq) / max_eq
    else:
        trade_rounds = db.query(models.TradeRound).filter(
            models.TradeRound.bot_id == bot_id
        ).all()

        # For overall drawdown, query the aggregated sessions.
        sessions = db.query(models.BotSession).filter(models.BotSession.bot_id == bot_id).all()
        if not sessions:
            drawdown = 0.0
        else:
            max_eq = max((s.max_equity for s in sessions if s.max_equity), default=1.0)
            min_eq = min((s.min_equity for s in sessions if s.min_equity), default=1.0)
            drawdown = 0.0 if max_eq <= 0 else (max_eq - min_eq) / max_eq

    # Realized PnL should come from closed trade rounds, not session aggregates.
    realized_pnl = float(sum(t.pnl for t in trade_rounds))

    total_trades = len(trade_rounds)
    win_rate = 0.0
    sharpe_ratio = 0.0

    if total_trades > 0:
        winning_trades = sum(1 for t in trade_rounds if t.pnl > 0)
        win_rate = winning_trades / total_trades
        
        returns = [t.pct_return for t in trade_rounds]
        std = np.std(returns, ddof=1) if len(returns) > 1 else 0.0
        if std > 0:
            mean_ret = np.mean(returns)
            sharpe_ratio = (mean_ret / std) * np.sqrt(len(returns))

    return schemas.BotKPIResponse(
        bot_id=bot_id,
        session_id=session_id,
        run_id=run_id,
        total_trades=total_trades,
        win_rate=win_rate,
        realized_pnl=realized_pnl,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=drawdown
    )

@app.post("/api/bots/{bot_id}/deposit", response_model=schemas.DepositResponse)
async def deposit_funds(bot_id: str, req: schemas.DepositRequest, db: Session = Depends(get_db)):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Update initial_capital (the base for dynamic cash computation)
    portfolio.initial_capital = (portfolio.initial_capital or 100000.0) + req.amount
    db.commit()
    db.refresh(portfolio)

    # Notify the C++ engine to update in-memory portfolio
    await deposit_queue.put({"bot_id": bot_id, "amount": req.amount})

    # Recompute current cash for response
    trades = db.query(models.Trade).filter(models.Trade.bot_id == bot_id).all()
    cash = portfolio.initial_capital
    for t in trades:
        value = t.price * t.qty
        if t.side in ("buy", "BUY"):
            cash -= value
        else:
            cash += value

    return schemas.DepositResponse(
        bot_id=bot_id,
        amount=req.amount,
        new_cash_balance=round(cash, 2)
    )

@app.post("/api/bots/{bot_id}/sessions/start", response_model=schemas.BotSessionResponse)
def start_lap_session(bot_id: str, db: Session = Depends(get_db)):
    bot = db.query(models.Bot).filter(models.Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    active_lap = db.query(models.BotSession).filter(
        models.BotSession.bot_id == bot_id,
        models.BotSession.session_type == "lap",
        models.BotSession.status == "active"
    ).first()

    if active_lap:
        raise HTTPException(status_code=400, detail="A lap session is already active for this bot.")

    portfolio = db.query(models.Portfolio).filter(models.Portfolio.bot_id == bot_id).first()
    starting_equity = portfolio.initial_capital if portfolio else 0.0

    session = models.BotSession(
        bot_id=bot_id,
        session_type="lap",
        starting_equity=starting_equity,
        max_equity=starting_equity,
        min_equity=starting_equity
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    
    return session

@app.post("/api/bots/{bot_id}/sessions/stop", response_model=schemas.BotSessionResponse)
def stop_lap_session(bot_id: str, db: Session = Depends(get_db)):
    session = db.query(models.BotSession).filter(
        models.BotSession.bot_id == bot_id,
        models.BotSession.session_type == "lap",
        models.BotSession.status == "active"
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="No active lap session found to stop.")

    session.status = "completed"
    session.end_time = func.now()
    db.commit()
    db.refresh(session)
    
    return session

@app.get("/api/bots/{bot_id}/sessions", response_model=List[schemas.BotSessionResponse])
def get_bot_sessions(
    bot_id: str,
    skip: int = 0,
    limit: int = 100,
    run_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.BotSession).filter(models.BotSession.bot_id == bot_id)
    if run_id:
        query = query.filter(models.BotSession.run_id == run_id)
    sessions = query.order_by(models.BotSession.start_time.desc()).offset(skip).limit(limit).all()
    return sessions


@app.post("/api/market-datasets", response_model=schemas.MarketDatasetResponse)
def create_market_dataset(payload: schemas.MarketDatasetCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    dataset = models.MarketDataset(**data)

    if dataset.file_path:
        summary = validate_replay_dataset(dataset.file_path)
        dataset.last_validated_at = datetime.datetime.now(datetime.timezone.utc)
        if summary.ok:
            dataset.status = "ready"
            dataset.validation_error = None
            dataset.event_count = summary.event_count
            dataset.start_time = summary.start_time
            dataset.end_time = summary.end_time
            if not dataset.symbols_json:
                dataset.symbols_json = json.dumps(summary.symbols)
        else:
            dataset.status = "invalid"
            dataset.validation_error = summary.error

    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


@app.get("/api/market-datasets", response_model=List[schemas.MarketDatasetResponse])
def list_market_datasets(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    datasets = db.query(models.MarketDataset).order_by(models.MarketDataset.created_at.desc()).offset(skip).limit(limit).all()
    return datasets


@app.get("/api/market-datasets/{dataset_id}", response_model=schemas.MarketDatasetResponse)
def get_market_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(models.MarketDataset).filter(models.MarketDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@app.post("/api/market-datasets/{dataset_id}/validate", response_model=schemas.DatasetValidationResponse)
def validate_market_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(models.MarketDataset).filter(models.MarketDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not dataset.file_path:
        raise HTTPException(status_code=400, detail="Dataset file_path is required for validation")

    summary = validate_replay_dataset(dataset.file_path)
    dataset.last_validated_at = datetime.datetime.now(datetime.timezone.utc)

    if summary.ok:
        dataset.status = "ready"
        dataset.validation_error = None
        dataset.event_count = summary.event_count
        dataset.start_time = summary.start_time
        dataset.end_time = summary.end_time
        dataset.symbols_json = json.dumps(summary.symbols)
    else:
        dataset.status = "invalid"
        dataset.validation_error = summary.error

    db.commit()
    db.refresh(dataset)

    return schemas.DatasetValidationResponse(
        ok=summary.ok,
        event_count=summary.event_count,
        symbols=summary.symbols,
        start_time=summary.start_time,
        end_time=summary.end_time,
        error=summary.error,
    )


@app.post("/api/replay/runs/from-candles", response_model=schemas.ReplayRunFromCandlesResponse)
def create_replay_run_from_candles(payload: schemas.ReplayRunFromCandlesRequest, db: Session = Depends(get_db)):
    if not ENABLE_SESSION_ORCHESTRATOR:
        raise HTTPException(
            status_code=400,
            detail="ENABLE_SESSION_ORCHESTRATOR must be enabled to run replay sessions.",
        )
    if not ENABLE_REPLAY_SESSIONS:
        raise HTTPException(
            status_code=400,
            detail="ENABLE_REPLAY_SESSIONS must be enabled to run replay sessions.",
        )
    if payload.replay_speed <= 0:
        raise HTTPException(status_code=400, detail="replay_speed must be > 0")
    if not payload.bot_ids:
        raise HTTPException(status_code=400, detail="bot_ids must include at least one bot")

    normalized_symbol = str(payload.symbol or "").upper().strip()
    if not normalized_symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    unique_bot_ids = list(dict.fromkeys(payload.bot_ids))
    bots = db.query(models.Bot).filter(models.Bot.id.in_(unique_bot_ids)).all()
    bot_by_id = {bot.id: bot for bot in bots}
    missing_bot_ids = [bot_id for bot_id in unique_bot_ids if bot_id not in bot_by_id]
    if missing_bot_ids:
        raise HTTPException(status_code=404, detail=f"Unknown bot ids: {', '.join(missing_bot_ids)}")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    dataset_id = str(uuid.uuid4())
    dataset_file_path = REPLAY_DATASETS_DIR / f"dataset_{dataset_id}.ndjson"

    candles_used = _write_replay_dataset_from_candles(
        dataset_path=dataset_file_path,
        symbol=normalized_symbol,
        candles=payload.candles,
        start_index=payload.start_index,
        end_index=payload.end_index,
    )

    summary = validate_replay_dataset(str(dataset_file_path))
    if not summary.ok:
        raise HTTPException(status_code=400, detail=summary.error or "Generated replay dataset is invalid")

    dataset = models.MarketDataset(
        id=dataset_id,
        name=payload.name or f"{normalized_symbol} replay {now_utc.strftime('%Y-%m-%d %H:%M:%S')}",
        description=(
            f"Generated from chart candles symbol={normalized_symbol} "
            f"range={payload.start_index}:{payload.end_index} tf={payload.timeframe_seconds}s"
        ),
        source_type="chart_replay",
        symbols_json=json.dumps([normalized_symbol]),
        start_time=summary.start_time,
        end_time=summary.end_time,
        event_count=summary.event_count,
        schema_version="v1",
        file_path=str(dataset_file_path),
        checksum=None,
        format_type="ndjson_v1",
        validation_error=None,
        last_validated_at=now_utc,
        status="ready",
    )
    db.add(dataset)
    db.flush()

    estimated_replay_seconds = max(
        30,
        int((max(candles_used, 1) * max(payload.timeframe_seconds, 1)) / payload.replay_speed) + 30,
    )
    run_start = now_utc + datetime.timedelta(seconds=1)
    run_end = run_start + datetime.timedelta(seconds=estimated_replay_seconds)

    template = models.SessionTemplate(
        name=f"{normalized_symbol} replay template {now_utc.strftime('%H:%M:%S')}",
        mode="replay",
        is_enabled="true",
        timezone=payload.timezone or "UTC",
        schedule_start_time=run_start,
        schedule_end_time=run_end,
        symbols_json=json.dumps([normalized_symbol]),
        launch_config_json=json.dumps({"symbol": normalized_symbol}),
        replay_dataset_id=dataset.id,
        replay_speed=payload.replay_speed,
    )
    db.add(template)
    db.flush()

    run = models.SessionRun(
        template_id=template.id,
        mode="replay",
        status="scheduled",
        timezone=template.timezone,
        scheduled_start_time=run_start,
        scheduled_end_time=run_end,
        replay_dataset_id=dataset.id,
        replay_speed=payload.replay_speed,
    )
    db.add(run)
    db.flush()

    for bot_id in unique_bot_ids:
        strategy_module = _resolve_strategy_module(template, bot_by_id[bot_id])
        db.add(
            models.SessionRunBot(
                run_id=run.id,
                bot_id=bot_id,
                status="pending",
                strategy_module=strategy_module,
            )
        )

    db.add(
        models.SessionRunEvent(
            run_id=run.id,
            event_type="state_transition",
            from_state=None,
            to_state="scheduled",
            message="Replay run created from frontend candle range",
            payload_json=json.dumps(
                {
                    "symbol": normalized_symbol,
                    "timeframe_seconds": payload.timeframe_seconds,
                    "range_start": payload.start_index,
                    "range_end": payload.end_index,
                    "candles_used": candles_used,
                }
            ),
        )
    )

    run.scheduled_start_time = now_utc
    old_state = run.status
    run.status = "starting"
    _create_state_event(db, run.id, old_state, run.status, "Replay run forced to start-now")

    db.commit()
    db.refresh(run)

    return schemas.ReplayRunFromCandlesResponse(
        run_id=run.id,
        dataset_id=dataset.id,
        template_id=template.id,
        status=run.status,
        replay_endpoint=run.replay_endpoint,
        candles_used=candles_used,
    )


@app.post("/api/session-templates", response_model=schemas.SessionTemplateResponse)
def create_session_template(payload: schemas.SessionTemplateCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    _validate_mode_fields(
        db=db,
        mode=data["mode"],
        schedule_start_time=data.get("schedule_start_time"),
        schedule_end_time=data.get("schedule_end_time"),
        replay_dataset_id=data.get("replay_dataset_id"),
        replay_speed=data.get("replay_speed"),
    )

    template = models.SessionTemplate(**data)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@app.get("/api/session-templates", response_model=List[schemas.SessionTemplateResponse])
def list_session_templates(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    templates = db.query(models.SessionTemplate).order_by(models.SessionTemplate.created_at.desc()).offset(skip).limit(limit).all()
    return templates


@app.get("/api/session-templates/{template_id}", response_model=schemas.SessionTemplateResponse)
def get_session_template(template_id: str, db: Session = Depends(get_db)):
    template = db.query(models.SessionTemplate).filter(models.SessionTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Session template not found")
    return template


@app.put("/api/session-templates/{template_id}", response_model=schemas.SessionTemplateResponse)
def update_session_template(template_id: str, payload: schemas.SessionTemplateUpdate, db: Session = Depends(get_db)):
    template = db.query(models.SessionTemplate).filter(models.SessionTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Session template not found")

    updates = payload.model_dump(exclude_unset=True)
    merged_mode = updates.get("mode", template.mode)
    merged_start = updates.get("schedule_start_time", template.schedule_start_time)
    merged_end = updates.get("schedule_end_time", template.schedule_end_time)
    merged_dataset_id = updates.get("replay_dataset_id", template.replay_dataset_id)
    merged_speed = updates.get("replay_speed", template.replay_speed)

    _validate_mode_fields(
        db=db,
        mode=merged_mode,
        schedule_start_time=merged_start,
        schedule_end_time=merged_end,
        replay_dataset_id=merged_dataset_id,
        replay_speed=merged_speed,
    )

    for key, value in updates.items():
        setattr(template, key, value)

    db.commit()
    db.refresh(template)
    return template


@app.delete("/api/session-templates/{template_id}")
def delete_session_template(template_id: str, db: Session = Depends(get_db)):
    template = db.query(models.SessionTemplate).filter(models.SessionTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Session template not found")
    db.delete(template)
    db.commit()
    return {"ok": True}


@app.post("/api/session-runs/from-template", response_model=schemas.SessionRunResponse)
def create_session_run_from_template(payload: schemas.SessionRunCreateFromTemplate, db: Session = Depends(get_db)):
    template = db.query(models.SessionTemplate).filter(models.SessionTemplate.id == payload.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Session template not found")

    run_start = payload.scheduled_start_time or template.schedule_start_time
    run_end = payload.scheduled_end_time or template.schedule_end_time

    _validate_mode_fields(
        db=db,
        mode=template.mode,
        schedule_start_time=run_start,
        schedule_end_time=run_end,
        replay_dataset_id=template.replay_dataset_id,
        replay_speed=template.replay_speed,
    )

    bot_ids = payload.bot_ids or []
    unique_bot_ids = list(dict.fromkeys(bot_ids))
    bot_by_id: Dict[str, models.Bot] = {}
    if unique_bot_ids:
        existing_bots = db.query(models.Bot).filter(models.Bot.id.in_(unique_bot_ids)).all()
        bot_by_id = {bot.id: bot for bot in existing_bots}
        existing_ids = set(bot_by_id.keys())
        missing = [bot_id for bot_id in unique_bot_ids if bot_id not in existing_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"Unknown bot ids: {', '.join(missing)}")

    run = models.SessionRun(
        template_id=template.id,
        mode=template.mode,
        status="scheduled",
        timezone=template.timezone,
        scheduled_start_time=run_start,
        scheduled_end_time=run_end,
        replay_dataset_id=template.replay_dataset_id,
        replay_speed=template.replay_speed,
    )
    db.add(run)
    db.flush()

    for bot_id in unique_bot_ids:
        strategy_module = _resolve_strategy_module(template, bot_by_id[bot_id])
        db.add(
            models.SessionRunBot(
                run_id=run.id,
                bot_id=bot_id,
                status="pending",
                strategy_module=strategy_module,
            )
        )

    db.add(
        models.SessionRunEvent(
            run_id=run.id,
            event_type="state_transition",
            from_state=None,
            to_state="scheduled",
            message="Run created from template",
            payload_json=None,
        )
    )

    db.commit()
    db.refresh(run)
    return run


@app.get("/api/session-runs", response_model=List[schemas.SessionRunResponse])
def list_session_runs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    runs = db.query(models.SessionRun).order_by(models.SessionRun.created_at.desc()).offset(skip).limit(limit).all()
    return runs


@app.get("/api/session-runs/{run_id}", response_model=schemas.SessionRunResponse)
def get_session_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(models.SessionRun).filter(models.SessionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Session run not found")
    return run


@app.get("/api/session-runs/{run_id}/events", response_model=List[schemas.SessionRunEventResponse])
def list_session_run_events(run_id: str, db: Session = Depends(get_db)):
    run = db.query(models.SessionRun).filter(models.SessionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Session run not found")

    events = db.query(models.SessionRunEvent).filter(models.SessionRunEvent.run_id == run_id).order_by(models.SessionRunEvent.created_at.asc()).all()
    return events


@app.get("/api/session-runs/{run_id}/bots", response_model=List[schemas.SessionRunBotResponse])
def list_session_run_bots(run_id: str, db: Session = Depends(get_db)):
    run = db.query(models.SessionRun).filter(models.SessionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Session run not found")
    assignments = db.query(models.SessionRunBot).filter(models.SessionRunBot.run_id == run_id).order_by(models.SessionRunBot.created_at.asc()).all()
    return assignments


@app.post("/api/session-runs/{run_id}/start-now", response_model=schemas.SessionRunResponse)
def start_session_run_now(run_id: str, db: Session = Depends(get_db)):
    run = db.query(models.SessionRun).filter(models.SessionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Session run not found")
    if run.status not in ("scheduled",):
        raise HTTPException(status_code=400, detail=f"Run is not startable from state '{run.status}'")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    run.scheduled_start_time = now_utc
    old_state = run.status
    run.status = "starting"
    _create_state_event(db, run.id, old_state, run.status, "Run forced to start-now")
    db.commit()
    db.refresh(run)
    return run


@app.post("/api/session-runs/{run_id}/cancel", response_model=schemas.SessionRunResponse)
async def cancel_session_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(models.SessionRun).filter(models.SessionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Session run not found")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if run.status in ("completed", "failed", "cancelled"):
        return run

    if run.status == "scheduled":
        old_state = run.status
        run.status = "cancelled"
        run.actual_end_time = now_utc
        _create_state_event(db, run.id, old_state, run.status, "Run cancelled before start")
        db.commit()
        db.refresh(run)
        return run

    old_state = run.status
    run.status = "stopping"
    _create_state_event(db, run.id, old_state, run.status, "Cancellation requested")
    await _stop_run_execution(db, run, now_utc)
    old_state = run.status
    run.status = "cancelled"
    _create_state_event(db, run.id, old_state, run.status, "Run cancelled by operator")
    db.commit()
    db.refresh(run)
    return run


@app.get("/api/session-runs/{run_id}/replay/control", response_model=schemas.ReplayControlResponse)
def get_replay_control(run_id: str):
    payload = _replay_manager.control_payload(run_id)
    return schemas.ReplayControlResponse(**payload)


@app.get("/api/system/health/session-orchestrator")
def get_orchestrator_health():
    db_check = "unknown"
    db_error = None
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA quick_check")).fetchone()
            db_check = result[0] if result else "unknown"
    except Exception as e:
        db_error = str(e)

    return {
        "orchestrator_enabled": ENABLE_SESSION_ORCHESTRATOR,
        "scheduled_live_enabled": ENABLE_SCHEDULED_LIVE_SESSIONS,
        "replay_enabled": ENABLE_REPLAY_SESSIONS,
        "scheduler_poll_seconds": SCHEDULER_POLL_SECONDS,
        "scheduler_max_retries": SCHEDULER_MAX_RETRIES,
        "active_process_runs": _bot_registry.active_run_count(),
        "active_process_bots": _bot_registry.active_bot_count(),
        "db_quick_check": db_check,
        "db_error": db_error,
    }
