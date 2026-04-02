from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import websockets

Message = dict[str, Any]
MessageHandler = Callable[[Message], Awaitable[None] | None]


@dataclass
class SyntheticBullClient:
    ws_url: str
    api_key: str = ""
    guest_mode: bool = False
    auto_reconnect: bool = True
    reconnect_min_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    heartbeat_interval: float = 15.0
    symbol_filter: set[str] | None = None

    on_message: MessageHandler | None = None
    on_welcome: MessageHandler | None = None
    on_orderbook: MessageHandler | None = None
    on_trade: MessageHandler | None = None
    on_candle: MessageHandler | None = None
    on_portfolio: MessageHandler | None = None
    on_open_orders: MessageHandler | None = None
    on_ack: MessageHandler | None = None
    on_cancel_ack: MessageHandler | None = None
    on_symbols: MessageHandler | None = None
    on_error: MessageHandler | None = None
    on_pong: MessageHandler | None = None
    on_connect: MessageHandler | None = None
    on_disconnect: MessageHandler | None = None
    on_reconnect: MessageHandler | None = None

    _ws: Any = field(init=False, default=None)
    _send_queue: asyncio.Queue[Message] = field(init=False, default_factory=asyncio.Queue)
    _connected: asyncio.Event = field(init=False, default_factory=asyncio.Event)
    _welcomed: asyncio.Event = field(init=False, default_factory=asyncio.Event)
    _stop_event: asyncio.Event = field(init=False, default_factory=asyncio.Event)
    _first_connect_complete: bool = field(init=False, default=False)

    user_id: str | None = field(init=False, default=None)
    symbol_prices: dict[str, float] = field(init=False, default_factory=dict)
    short_selling_config: dict[str, Any] = field(init=False, default_factory=dict)
    latest_portfolio: Message | None = field(init=False, default=None)
    latest_open_orders: list[dict[str, Any]] = field(init=False, default_factory=list)

    async def run_forever(self) -> None:
        if not self.guest_mode and not self.api_key:
            raise ValueError("api_key is required unless guest_mode=True")

        backoff = max(self.reconnect_min_delay, 0.1)
        max_backoff = max(self.reconnect_max_delay, backoff)

        while not self._stop_event.is_set():
            disconnect_reason = "connection closed"
            try:
                async with websockets.connect(self.ws_url, ping_interval=None) as ws:
                    self._ws = ws
                    self._connected.set()
                    await self._emit(self.on_connect, {"type": "connect", "ws_url": self.ws_url})

                    if self.guest_mode:
                        await self._send_now({"type": "guest_login"})
                    else:
                        await self._send_now({"type": "auth", "api_key": self.api_key})

                    if self._first_connect_complete:
                        await self._emit(self.on_reconnect, {"type": "reconnect", "ws_url": self.ws_url})
                    self._first_connect_complete = True

                    backoff = max(self.reconnect_min_delay, 0.1)

                    recv_task = asyncio.create_task(self._recv_loop())
                    send_task = asyncio.create_task(self._send_loop())
                    keepalive_task = asyncio.create_task(self._keepalive_loop())

                    done, pending = await asyncio.wait(
                        {recv_task, send_task, keepalive_task},
                        return_when=asyncio.FIRST_EXCEPTION,
                    )

                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

                    for task in done:
                        exc = task.exception()
                        if exc is not None:
                            raise exc

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                disconnect_reason = str(exc)
                if not self.auto_reconnect or self._stop_event.is_set():
                    raise
            finally:
                self._connected.clear()
                self._welcomed.clear()
                self._ws = None
                self._drain_send_queue()
                await self._emit(
                    self.on_disconnect,
                    {"type": "disconnect", "reason": disconnect_reason},
                )

            if not self.auto_reconnect or self._stop_event.is_set():
                break

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, max_backoff)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._ws is not None:
            await self._ws.close()

    async def close(self) -> None:
        await self.stop()

    def start(self) -> asyncio.Task[None]:
        return asyncio.create_task(self.run_forever())

    async def wait_until_connected(self) -> None:
        await self._connected.wait()

    async def wait_until_welcome(self) -> None:
        await self._welcomed.wait()

    async def send(self, payload: Message) -> None:
        await self._send_queue.put(payload)

    async def place_limit(self, symbol: str, side: str, price: float, qty: float) -> None:
        await self.send(
            {
                "type": "place_order",
                "symbol": symbol,
                "order_type": "limit",
                "side": side,
                "price": round(price, 2),
                "qty": round(qty, 5),
            }
        )

    async def place_market(self, symbol: str, side: str, qty: float) -> None:
        await self.send(
            {
                "type": "place_order",
                "symbol": symbol,
                "order_type": "market",
                "side": side,
                "qty": round(qty, 5),
            }
        )

    async def cancel(self, symbol: str, order_id: int) -> None:
        await self.send(
            {
                "type": "cancel_order",
                "symbol": symbol,
                "order_id": int(order_id),
            }
        )

    async def get_symbols(self) -> None:
        await self.send({"type": "get_symbols"})

    async def deposit(self, bot_id: str, amount: float) -> None:
        await self.send({"type": "deposit", "bot_id": bot_id, "amount": amount})

    async def ping(self) -> None:
        await self.send({"type": "ping"})

    async def _recv_loop(self) -> None:
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    continue
                await self._handle_message(msg)
            except Exception as exc:
                await self._emit(
                    self.on_error,
                    {"type": "error", "message": f"message decode failure: {exc}"},
                )

    async def _send_loop(self) -> None:
        while True:
            payload = await self._send_queue.get()
            await self._send_now(payload)

    async def _keepalive_loop(self) -> None:
        if self.heartbeat_interval <= 0:
            return
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            await self.send({"type": "ping"})

    async def _send_now(self, payload: Message) -> None:
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        await self._ws.send(json.dumps(payload))

    async def _handle_message(self, msg: Message) -> None:
        msg_type = str(msg.get("type", ""))

        if msg_type in {"orderbook", "trade", "candle"} and self.symbol_filter:
            symbol = str(msg.get("symbol", ""))
            if symbol not in self.symbol_filter:
                return

        if msg_type == "welcome":
            self.user_id = msg.get("user_id")
            self.symbol_prices = {
                entry.get("symbol", ""): float(entry.get("price", 0.0))
                for entry in msg.get("symbols", [])
                if isinstance(entry, dict) and entry.get("symbol")
            }
            short_cfg = msg.get("short_selling")
            self.short_selling_config = short_cfg if isinstance(short_cfg, dict) else {}
            self._welcomed.set()

        if msg_type == "portfolio":
            self.latest_portfolio = msg

        if msg_type == "open_orders":
            orders = msg.get("orders", [])
            if isinstance(orders, list):
                self.latest_open_orders = [o for o in orders if isinstance(o, dict)]

        await self._emit(self.on_message, msg)

        if msg_type == "welcome":
            await self._emit(self.on_welcome, msg)
        elif msg_type == "orderbook":
            await self._emit(self.on_orderbook, msg)
        elif msg_type == "trade":
            await self._emit(self.on_trade, msg)
        elif msg_type == "candle":
            await self._emit(self.on_candle, msg)
        elif msg_type == "portfolio":
            await self._emit(self.on_portfolio, msg)
        elif msg_type == "open_orders":
            await self._emit(self.on_open_orders, msg)
        elif msg_type == "ack":
            await self._emit(self.on_ack, msg)
        elif msg_type == "cancel_ack":
            await self._emit(self.on_cancel_ack, msg)
        elif msg_type == "symbols":
            await self._emit(self.on_symbols, msg)
        elif msg_type == "error":
            await self._emit(self.on_error, msg)
        elif msg_type == "pong":
            await self._emit(self.on_pong, msg)

    async def _emit(self, handler: MessageHandler | None, msg: Message) -> None:
        if handler is None:
            return
        try:
            maybe_awaitable = handler(msg)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except Exception as exc:
            print(f"[SyntheticBullClient] Handler error for '{msg.get('type', 'unknown')}': {exc}")

    def _drain_send_queue(self) -> None:
        while not self._send_queue.empty():
            try:
                self._send_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
