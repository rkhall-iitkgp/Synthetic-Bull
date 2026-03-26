"""
Market Maker Bot - main event loop.

Run with:
    python -m market_maker.main
"""

import asyncio

from market_maker.inventory_manager import InventoryManager
from market_maker.kpi_tracker import MMKPITracker
from market_maker.order_tracker import OrderTracker
from market_maker.spread_calculator import SpreadCalculator
from market_maker.status_server import run as run_status_server
from market_maker.status_server import update_status
from shared.config import MM_REQUOTE_INTERVAL, MM_SYMBOL, STARTING_EQUITY
from shared.exchange_client import ExchangeClient


class MarketMakerBot:
    def __init__(self):
        self.symbol: str = MM_SYMBOL
        self.client = ExchangeClient(on_message=self._handle_message)
        self.inventory = InventoryManager(symbol=MM_SYMBOL)
        self.spread = SpreadCalculator()
        self.tracker = OrderTracker()
        self.kpi = MMKPITracker()
        self.latest_mid: float = 0.0
        self.last_mid_quoted: float = 0.0
        self._requote_lock: asyncio.Lock = asyncio.Lock()

    async def run(self):
        await asyncio.gather(
            self.client.run(),
            self._requote_loop(),
            run_status_server(),
        )

    async def _requote_loop(self):
        await self.client.wait_until_connected()
        await asyncio.sleep(1.0)
        while True:
            await asyncio.sleep(MM_REQUOTE_INTERVAL)
            await self._do_requote()

    async def _do_requote(self):
        async with self._requote_lock:
            if self.latest_mid == 0.0:
                return
            if self.tracker.has_pending():
                return

            for oid in self.tracker.get_all_ids():
                await self.client.cancel(self.symbol, oid)

            await asyncio.sleep(0.05)
            self.tracker.clear()

            skew = self.inventory.skew_factor()
            is_too_long = self.inventory.is_too_long()
            is_too_short = self.inventory.is_too_short()

            quotes = self.spread.compute(self.latest_mid, skew, is_too_long, is_too_short)

            if not is_too_long:
                await self.client.place_limit(
                    self.symbol,
                    "buy",
                    quotes["bid_price"],
                    quotes["bid_qty"],
                )
                self.tracker.register_sent("bid")

            if not is_too_short:
                await self.client.place_limit(
                    self.symbol,
                    "sell",
                    quotes["ask_price"],
                    quotes["ask_qty"],
                )
                self.tracker.register_sent("ask")

            self.last_mid_quoted = self.latest_mid

    async def _handle_message(self, msg: dict):
        t = msg.get("type")

        if t == "welcome":
            self.client.user_id = msg.get("user_id")
            return

        if t == "portfolio":
            self.inventory.on_portfolio_update(msg)
            self.kpi.record_equity(msg["total_value"])
            self._update_status()
            return

        if t == "open_orders":
            await self._on_open_orders(msg)
            return

        if t == "error":
            print(f"[MMBot] Exchange error: {msg.get('message')}")
            return

        if t == "pong":
            return

        if msg.get("symbol") != self.symbol:
            return

        if t == "orderbook":
            self.latest_mid = float(msg.get("mid", self.latest_mid))
            if self.last_mid_quoted > 0:
                move = abs(self.latest_mid - self.last_mid_quoted) / self.last_mid_quoted
                if move > 0.001:
                    asyncio.create_task(self._do_requote())

        elif t == "trade":
            await self._on_trade(msg)

        elif t == "ack":
            self.tracker.on_ack(int(msg["order_id"]))

        elif t == "cancel_ack":
            self.tracker.on_cancel_ack(int(msg["order_id"]))

    async def _on_open_orders(self, msg: dict):
        orders = msg.get("orders", [])
        self.tracker.clear()
        for o in orders:
            if o.get("symbol") != self.symbol:
                continue
            self.tracker.on_ack(o["order_id"])
            print(f"[MMBot] Restored order {o['order_id']} {o['side']} @ {o['price']} from open_orders")

    def _reset_for_new_session(self):
        self.inventory = InventoryManager(symbol=self.symbol)
        self.tracker.clear()
        self.kpi = MMKPITracker()
        self.latest_mid = 0.0
        self.last_mid_quoted = 0.0
        self.kpi.record_equity(STARTING_EQUITY)
        self._update_status()

    async def _on_trade(self, msg: dict):
        if self.client.user_id is None:
            return

        price = float(msg["price"])
        qty = float(msg["qty"])

        if msg.get("buyer") == self.client.user_id:
            self.kpi.on_fill("bid", price, qty, 0.0)

        if msg.get("seller") == self.client.user_id:
            self.kpi.on_fill("ask", price, qty, 0.0)

    def _update_status(self):
        update_status(self.kpi.get_status(self.inventory.total_val, self.inventory.holdings))


async def main():
    bot = MarketMakerBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
