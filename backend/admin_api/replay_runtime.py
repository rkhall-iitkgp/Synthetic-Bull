import asyncio
import datetime
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set


ALLOWED_EVENT_TYPES = {"orderbook", "candle", "trade"}


@dataclass
class ReplayEvent:
    ts_us: int
    symbol: str
    payload: Dict[str, Any]


@dataclass
class ReplayDatasetSummary:
    ok: bool
    event_count: int
    symbols: List[str]
    start_time: Optional[datetime.datetime]
    end_time: Optional[datetime.datetime]
    error: Optional[str]
    events: List[ReplayEvent] = field(default_factory=list)


@dataclass
class ReplayClient:
    bot_id: str
    user_id: str
    cash: float
    holdings: Dict[str, float] = field(default_factory=dict)
    avg_cost: Dict[str, float] = field(default_factory=dict)
    next_order_id: int = 1


class ReplayRunState:
    def __init__(self, run_id: str, speed: float, events: List[ReplayEvent]):
        self.run_id = run_id
        self.speed = max(speed, 0.1)
        self.events = events
        self.events_sent = 0
        self.status = "ready"
        self.cursor = 0
        self.started_monotonic = 0.0
        self.clients: Dict[int, ReplayClient] = {}
        self.latest_mid_by_symbol: Dict[str, float] = {}
        self.symbols: Set[str] = {ev.symbol for ev in events}
        self.playback_task: Optional[asyncio.Task] = None
        self.next_trade_id = 1
        self._lock = asyncio.Lock()

    def _event_elapsed_seconds(self, ts_us: int) -> float:
        if not self.events:
            return 0.0
        start_us = self.events[0].ts_us
        return max(0.0, (ts_us - start_us) / 1_000_000.0)

    async def start(self):
        if self.playback_task and not self.playback_task.done():
            return
        self.status = "running"
        self.started_monotonic = time.monotonic()
        self.playback_task = asyncio.create_task(self._playback_loop())

    async def stop(self):
        self.status = "stopped"
        if self.playback_task and not self.playback_task.done():
            self.playback_task.cancel()
            try:
                await self.playback_task
            except Exception:
                pass

    def add_client(self, websocket_id: int, client: ReplayClient):
        self.clients[websocket_id] = client

    def remove_client(self, websocket_id: int):
        self.clients.pop(websocket_id, None)

    def current_mid(self, symbol: str) -> float:
        if symbol in self.latest_mid_by_symbol:
            return self.latest_mid_by_symbol[symbol]
        if self.events:
            for ev in self.events:
                if ev.symbol == symbol:
                    if ev.payload.get("type") == "orderbook":
                        return float(ev.payload.get("mid", 0.0))
                    if ev.payload.get("type") == "candle":
                        return float(ev.payload.get("c", 0.0))
                    if ev.payload.get("type") == "trade":
                        return float(ev.payload.get("price", 0.0))
        return 0.0

    async def _playback_loop(self):
        while self.cursor < len(self.events) and self.status == "running":
            ev = self.events[self.cursor]
            target_elapsed = self._event_elapsed_seconds(ev.ts_us)
            live_elapsed = (time.monotonic() - self.started_monotonic) * self.speed

            if target_elapsed > live_elapsed:
                await asyncio.sleep(min(0.2, target_elapsed - live_elapsed))
                continue

            await self.broadcast(ev.payload)
            self._update_market_state(ev.payload)
            self.cursor += 1
            self.events_sent = self.cursor

        if self.status == "running":
            self.status = "completed"

    def _update_market_state(self, payload: Dict[str, Any]):
        event_type = payload.get("type")
        symbol = payload.get("symbol")
        if not symbol:
            return

        if event_type == "orderbook":
            self.latest_mid_by_symbol[symbol] = float(payload.get("mid", 0.0))
        elif event_type == "candle":
            self.latest_mid_by_symbol[symbol] = float(payload.get("c", 0.0))
        elif event_type == "trade":
            self.latest_mid_by_symbol[symbol] = float(payload.get("price", 0.0))

    async def broadcast(self, payload: Dict[str, Any]):
        stale_client_ids: List[int] = []
        for ws_id, _client in list(self.clients.items()):
            websocket = _REPLAY_WEBSOCKET_REGISTRY.get(ws_id)
            if websocket is None:
                stale_client_ids.append(ws_id)
                continue
            try:
                await websocket.send_json(payload)
            except Exception:
                stale_client_ids.append(ws_id)

        for stale_id in stale_client_ids:
            self.remove_client(stale_id)
            _REPLAY_WEBSOCKET_REGISTRY.pop(stale_id, None)


class ReplayManager:
    def __init__(self):
        self._runs: Dict[str, ReplayRunState] = {}

    def get_run(self, run_id: str) -> Optional[ReplayRunState]:
        return self._runs.get(run_id)

    async def stop_run(self, run_id: str):
        run_state = self._runs.get(run_id)
        if not run_state:
            return
        await run_state.stop()
        self._runs.pop(run_id, None)

    async def create_or_replace_run(self, run_id: str, speed: float, dataset_path: str) -> ReplayRunState:
        await self.stop_run(run_id)
        summary = validate_replay_dataset(dataset_path)
        if not summary.ok:
            raise RuntimeError(summary.error or "Invalid replay dataset")

        state = ReplayRunState(run_id=run_id, speed=speed, events=summary.events)
        self._runs[run_id] = state
        await state.start()
        return state

    def control_payload(self, run_id: str) -> Dict[str, Any]:
        run_state = self._runs.get(run_id)
        if not run_state:
            return {
                "run_id": run_id,
                "ready": False,
                "clients": 0,
                "events_total": 0,
                "events_sent": 0,
                "status": "missing",
            }
        return {
            "run_id": run_id,
            "ready": True,
            "clients": len(run_state.clients),
            "events_total": len(run_state.events),
            "events_sent": run_state.events_sent,
            "status": run_state.status,
        }


_REPLAY_WEBSOCKET_REGISTRY: Dict[int, Any] = {}


def _normalize_ts_us(event: Dict[str, Any]) -> Optional[int]:
    ts = event.get("ts")
    if ts is None:
        ts = event.get("t")
    if ts is None:
        return None

    try:
        ts_int = int(ts)
    except Exception:
        return None

    # Heuristic conversion to microseconds.
    if ts_int < 10_000_000_000:
        return ts_int * 1_000_000
    if ts_int < 10_000_000_000_000:
        return ts_int * 1_000
    return ts_int


def _to_datetime(ts_us: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ts_us / 1_000_000.0, tz=datetime.timezone.utc)


def validate_replay_dataset(dataset_path: str) -> ReplayDatasetSummary:
    path = Path(dataset_path)
    if not path.exists():
        return ReplayDatasetSummary(
            ok=False,
            event_count=0,
            symbols=[],
            start_time=None,
            end_time=None,
            error=f"Dataset file not found: {dataset_path}",
            events=[],
        )

    events: List[ReplayEvent] = []
    symbols: Set[str] = set()
    last_ts_us = -1

    try:
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError as decode_error:
                    return ReplayDatasetSummary(
                        ok=False,
                        event_count=0,
                        symbols=[],
                        start_time=None,
                        end_time=None,
                        error=f"Line {line_no}: invalid JSON ({decode_error})",
                        events=[],
                    )

                event_type = event.get("type")
                if event_type not in ALLOWED_EVENT_TYPES:
                    return ReplayDatasetSummary(
                        ok=False,
                        event_count=0,
                        symbols=[],
                        start_time=None,
                        end_time=None,
                        error=f"Line {line_no}: unsupported event type '{event_type}'",
                        events=[],
                    )

                symbol = event.get("symbol")
                if not symbol or not isinstance(symbol, str):
                    return ReplayDatasetSummary(
                        ok=False,
                        event_count=0,
                        symbols=[],
                        start_time=None,
                        end_time=None,
                        error=f"Line {line_no}: missing or invalid symbol",
                        events=[],
                    )

                ts_us = _normalize_ts_us(event)
                if ts_us is None:
                    return ReplayDatasetSummary(
                        ok=False,
                        event_count=0,
                        symbols=[],
                        start_time=None,
                        end_time=None,
                        error=f"Line {line_no}: missing or invalid timestamp",
                        events=[],
                    )

                if ts_us < last_ts_us:
                    return ReplayDatasetSummary(
                        ok=False,
                        event_count=0,
                        symbols=[],
                        start_time=None,
                        end_time=None,
                        error=(
                            f"Line {line_no}: timestamps must be non-decreasing "
                            f"(got {ts_us} after {last_ts_us})"
                        ),
                        events=[],
                    )

                # Ensure a compatible payload schema for replay broadcasting.
                payload = dict(event)
                payload["type"] = event_type
                payload["symbol"] = symbol
                if "ts" not in payload:
                    payload["ts"] = ts_us

                if event_type == "orderbook":
                    if "mid" not in payload:
                        return ReplayDatasetSummary(
                            ok=False,
                            event_count=0,
                            symbols=[],
                            start_time=None,
                            end_time=None,
                            error=f"Line {line_no}: orderbook event missing mid",
                            events=[],
                        )
                    payload.setdefault("spread", 0.0)
                    payload.setdefault("bids", [])
                    payload.setdefault("asks", [])

                if event_type == "candle":
                    if "c" not in payload:
                        return ReplayDatasetSummary(
                            ok=False,
                            event_count=0,
                            symbols=[],
                            start_time=None,
                            end_time=None,
                            error=f"Line {line_no}: candle event missing close 'c'",
                            events=[],
                        )
                    payload.setdefault("o", payload["c"])
                    payload.setdefault("h", payload["c"])
                    payload.setdefault("l", payload["c"])
                    payload.setdefault("v", 0.0)
                    payload.setdefault("t", int(ts_us / 1000))

                if event_type == "trade":
                    if "price" not in payload or "qty" not in payload:
                        return ReplayDatasetSummary(
                            ok=False,
                            event_count=0,
                            symbols=[],
                            start_time=None,
                            end_time=None,
                            error=f"Line {line_no}: trade event missing price or qty",
                            events=[],
                        )
                    payload.setdefault("id", 0)
                    payload.setdefault("buyer", "replay_buyer")
                    payload.setdefault("seller", "replay_seller")

                events.append(ReplayEvent(ts_us=ts_us, symbol=symbol, payload=payload))
                symbols.add(symbol)
                last_ts_us = ts_us

    except Exception as file_error:
        return ReplayDatasetSummary(
            ok=False,
            event_count=0,
            symbols=[],
            start_time=None,
            end_time=None,
            error=f"Dataset read failed: {file_error}",
            events=[],
        )

    if not events:
        return ReplayDatasetSummary(
            ok=False,
            event_count=0,
            symbols=[],
            start_time=None,
            end_time=None,
            error="Dataset has no events",
            events=[],
        )

    return ReplayDatasetSummary(
        ok=True,
        event_count=len(events),
        symbols=sorted(symbols),
        start_time=_to_datetime(events[0].ts_us),
        end_time=_to_datetime(events[-1].ts_us),
        error=None,
        events=events,
    )


def register_replay_websocket(websocket: Any):
    _REPLAY_WEBSOCKET_REGISTRY[id(websocket)] = websocket


def unregister_replay_websocket(websocket: Any):
    _REPLAY_WEBSOCKET_REGISTRY.pop(id(websocket), None)


def build_portfolio_payload(client: ReplayClient, latest_mid_by_symbol: Dict[str, float]) -> Dict[str, Any]:
    positions = {}
    holdings_value = 0.0

    for symbol, qty in client.holdings.items():
        if abs(qty) < 1e-12:
            continue
        mid = float(latest_mid_by_symbol.get(symbol, 0.0))
        avg = float(client.avg_cost.get(symbol, 0.0))
        holdings_value += qty * mid
        positions[symbol] = {
            "qty": qty,
            "avg_cost": avg,
            "mark": mid,
        }

    total_value = client.cash + holdings_value
    return {
        "type": "portfolio",
        "cash": round(client.cash, 6),
        "holdings": round(sum(client.holdings.values()), 6),
        "avg_cost": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_value": round(total_value, 6),
        "positions": positions,
    }


def apply_fill(client: ReplayClient, symbol: str, side: str, exec_price: float, qty: float):
    prev_qty = float(client.holdings.get(symbol, 0.0))
    prev_avg = float(client.avg_cost.get(symbol, 0.0))
    notional = exec_price * qty

    if side == "buy":
        client.cash -= notional
        new_qty = prev_qty + qty
        if new_qty != 0:
            if prev_qty >= 0:
                client.avg_cost[symbol] = ((prev_qty * prev_avg) + (qty * exec_price)) / new_qty
            else:
                client.avg_cost[symbol] = exec_price
        client.holdings[symbol] = new_qty
    else:
        client.cash += notional
        new_qty = prev_qty - qty
        if new_qty != 0 and prev_qty <= 0:
            client.avg_cost[symbol] = ((abs(prev_qty) * prev_avg) + (qty * exec_price)) / abs(new_qty)
        elif new_qty == 0:
            client.avg_cost[symbol] = 0.0
        client.holdings[symbol] = new_qty


def choose_exec_price(run_state: ReplayRunState, symbol: str, payload: Dict[str, Any]) -> float:
    order_type = payload.get("order_type")
    if order_type == "market":
        return float(run_state.current_mid(symbol))
    return float(payload.get("price", run_state.current_mid(symbol)))


def order_to_trade_payload(
    run_state: ReplayRunState,
    client: ReplayClient,
    symbol: str,
    side: str,
    exec_price: float,
    qty: float,
) -> Dict[str, Any]:
    trade_id = run_state.next_trade_id
    run_state.next_trade_id += 1

    if side == "buy":
        buyer = client.user_id
        seller = "replay_liquidity"
    else:
        buyer = "replay_liquidity"
        seller = client.user_id

    return {
        "type": "trade",
        "id": trade_id,
        "symbol": symbol,
        "price": round(exec_price, 6),
        "qty": round(qty, 6),
        "buyer": buyer,
        "seller": seller,
        "ts": int(time.time() * 1_000_000),
    }
