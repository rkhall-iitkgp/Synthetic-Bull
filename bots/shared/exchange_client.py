import asyncio
import json
from typing import Awaitable, Callable

import websockets

from shared.config import EXCHANGE_WS_URL


class ExchangeClient:
    """
    Manages one persistent WebSocket connection to ws://localhost:9001.

    Usage:
        client = ExchangeClient(on_message=my_handler)
        await client.run()          # blocks forever, reconnects on drop

    Sending:
        await client.send({"type": "place_order", ...})
        await client.cancel(order_id: int)
        await client.ping()

    The on_message coroutine receives one parsed dict per message.
    """

    def __init__(self, on_message: Callable[[dict], Awaitable[None]]):
        self.on_message = on_message
        self.user_id: str | None = None
        self._symbol_prices: dict[str, float] = {}
        self._ws = None
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._connected = asyncio.Event()

    async def run(self):
        """Connect loop with exponential backoff. Never returns."""
        backoff = 1
        while True:
            try:
                async with websockets.connect(EXCHANGE_WS_URL) as ws:
                    self._ws = ws
                    self._connected.set()
                    backoff = 1
                    print(f"[ExchangeClient] Connected to {EXCHANGE_WS_URL}")
                    await asyncio.gather(
                        self._recv_loop(ws),
                        self._send_loop(ws),
                        self._keepalive_loop(),
                    )
            except Exception as e:
                self._connected.clear()
                self._ws = None
                print(f"[ExchangeClient] Disconnected: {e} - retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _recv_loop(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "welcome":
                    self.user_id = msg.get("user_id")
                    for entry in msg.get("symbols", []):
                        self._symbol_prices[entry["symbol"]] = entry["price"]
                await self.on_message(msg)
            except Exception as e:
                print(f"[ExchangeClient] Message error: {e}")

    async def _send_loop(self, ws):
        while True:
            payload = await self._send_queue.get()
            try:
                await ws.send(json.dumps(payload))
            except Exception as e:
                print(f"[ExchangeClient] Send error: {e}")

    async def _keepalive_loop(self):
        while True:
            await asyncio.sleep(15)
            await self.send({"type": "ping"})

    async def send(self, payload: dict):
        await self._send_queue.put(payload)

    async def place_limit(self, symbol: str, side: str, price: float, qty: float):
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

    async def place_market(self, symbol: str, side: str, qty: float):
        await self.send(
            {
                "type": "place_order",
                "symbol": symbol,
                "order_type": "market",
                "side": side,
                "qty": round(qty, 5),
            }
        )

    async def cancel(self, symbol: str, order_id: int):
        await self.send(
            {
                "type": "cancel_order",
                "symbol": symbol,
                "order_id": order_id,
            }
        )

    def get_initial_price(self, symbol: str) -> float | None:
        return self._symbol_prices.get(symbol)

    async def ping(self):
        await self.send({"type": "ping"})

    async def wait_until_connected(self):
        await self._connected.wait()
