"""
Custom Bot - skeleton for your own trading strategy.

Run with:
    python -m custom.main

This bot connects to the exchange, receives market data, and provides
a simple structure for you to implement your own trading logic.
Modify the _on_candle() and _on_trade() methods to build your strategy.
"""

import asyncio

from custom.status_server import run as run_status_server
from custom.status_server import update_status
from shared.config import (
    CUSTOM_BOT_API_KEY,
    CUSTOM_SYMBOL,
    PNL_FLOOR,
    STARTING_EQUITY,
)
from shared.exchange_client import ExchangeClient


class CustomBot:
    def __init__(self):
        self.symbol: str = CUSTOM_SYMBOL
        self.client = ExchangeClient(
            on_message=self._handle_message,
            on_reconnect=self._on_reconnect,
            api_key=CUSTOM_BOT_API_KEY,
        )
        self.latest_mid: float = 0.0
        self.latest_bids: list = []
        self.latest_asks: list = []
        self.cash: float = STARTING_EQUITY
        self.holdings: float = 0.0
        self._halted: bool = False

    async def run(self):
        await asyncio.gather(
            self.client.run(),
            run_status_server(),
        )

    async def _on_reconnect(self):
        print("[CustomBot] Reconnect detected")

    async def _handle_message(self, msg: dict):
        t = msg.get("type")

        if t == "welcome":
            self.client.user_id = msg.get("user_id")
            return

        if t == "portfolio":
            self.cash = float(msg.get("cash", self.cash))
            self.holdings = sum(
                float(p.get("quantity", 0))
                for p in msg.get("positions", [])
                if p.get("symbol") == self.symbol
            )
            self._check_pnl_floor()
            self._update_status()
            return

        if t in ("error", "pong", "open_orders"):
            return

        if msg.get("symbol") != self.symbol:
            return

        if t == "orderbook":
            self.latest_mid = float(msg.get("mid", self.latest_mid))
            self.latest_bids = msg.get("bids", [])
            self.latest_asks = msg.get("asks", [])

        elif t == "candle":
            await self._on_candle(msg)

        elif t == "trade":
            await self._on_trade(msg)

    async def _on_candle(self, msg: dict):
        """
        Called on every 1-second candle for your symbol.

        msg keys: symbol, o (open), h (high), l (low), c (close), v (volume), t (timestamp)

        Implement your strategy here. Example:
            close = float(msg["c"])
            if some_condition:
                await self.client.place_market(self.symbol, "buy", 0.01)
        """
        pass

    async def _on_trade(self, msg: dict):
        """
        Called on every trade event for your symbol.

        msg keys: symbol, price, qty, buyer, seller, trade_id
        """
        pass

    def _check_pnl_floor(self):
        equity = self.cash + (self.holdings * self.latest_mid if self.latest_mid > 0 else 0)
        if not self._halted and equity < PNL_FLOOR:
            self._halted = True
            print(f"[CustomBot] PNL FLOOR HIT — equity ${equity:.2f} < ${PNL_FLOOR:.2f}. Halted.")

    def _update_status(self):
        equity = self.cash + (self.holdings * self.latest_mid if self.latest_mid > 0 else 0)
        update_status({
            "equity": equity,
            "pnl": equity - STARTING_EQUITY,
            "position": "FLAT" if self.holdings == 0 else ("LONG" if self.holdings > 0 else "SHORT"),
            "halted": self._halted,
        })


async def main():
    bot = CustomBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
