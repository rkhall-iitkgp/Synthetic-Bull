"""
Market Maker Bot - main event loop.

Run with:
    python -m market_maker.main

Key profitability improvements:
  - Cancel-then-place requote with minimal delay
  - PnL floor halt at $80k
  - Cancel-all-open-orders on reconnect
  - Aggressive spread widening at high inventory
"""

import asyncio

from market_maker.inventory_manager import InventoryManager
from market_maker.kpi_tracker import MMKPITracker
from market_maker.order_tracker import OrderTracker
from market_maker.spread_calculator import SpreadCalculator
from market_maker.status_server import run as run_status_server
from market_maker.status_server import update_status
from shared.config import MM_QUOTE_QTY, MM_REQUOTE_INTERVAL, MM_SYMBOL, PNL_FLOOR, STARTING_EQUITY
from shared.exchange_client import ExchangeClient


class MarketMakerBot:
    def __init__(self):
        self.symbol: str = MM_SYMBOL
        self.client = ExchangeClient(
            on_message=self._handle_message,
            on_reconnect=self._on_reconnect,
        )
        self.inventory = InventoryManager(symbol=MM_SYMBOL)
        self.spread = SpreadCalculator()
        self.tracker = OrderTracker()
        self.kpi = MMKPITracker()
        self.latest_mid: float = 0.0
        self.last_mid_quoted: float = 0.0
        self._requote_lock: asyncio.Lock = asyncio.Lock()
        self._halted: bool = False
        self._initial_sync_done: bool = False
        self._seed_order_sent: bool = False

    async def run(self):
        await asyncio.gather(
            self.client.run(),
            self._requote_loop(),
            run_status_server(),
        )

    async def _on_reconnect(self):
        """Cancel all known orders on reconnect to prevent orphaned positions."""
        print("[MMBot] Reconnect detected — cancelling all tracked orders")
        for oid in self.tracker.get_all_ids():
            await self.client.cancel(self.symbol, oid)
        self.tracker.clear()
        self.last_mid_quoted = 0.0
        self._initial_sync_done = False
        self._seed_order_sent = False

    async def _requote_loop(self):
        await self.client.wait_until_connected()
        # Wait for the first orderbook to arrive (server replays ~1800 candles first)
        print(f"[MMBot] Waiting for first {self.symbol} orderbook...")
        while self.latest_mid == 0.0:
            await asyncio.sleep(0.5)
        print(f"[MMBot] Got first {self.symbol} mid={self.latest_mid:.2f} — starting requote loop")
        while True:
            await asyncio.sleep(MM_REQUOTE_INTERVAL)
            await self._do_requote()

    async def _do_requote(self):
        async with self._requote_lock:
            if self.latest_mid == 0.0:
                return
            if self.tracker.has_pending():
                return
            if self._halted:
                return

            # Bootstrap inventory once so we can quote both sides.
            # Without this, the bot can stay one-sided (buy-only) for long periods and show no fills.
            if (not self._seed_order_sent) and (self.inventory.holdings < MM_QUOTE_QTY * 0.5):
                seed_qty = max(0.001, round(MM_QUOTE_QTY, 4))
                print(f"[MMBot] Bootstrap inventory via market buy qty={seed_qty:.4f}")
                await self.client.place_market(self.symbol, "buy", seed_qty)
                self._seed_order_sent = True
                return

            # CANCEL old orders first
            old_ids = self.tracker.get_all_ids()
            for oid in old_ids:
                await self.client.cancel(self.symbol, oid)

            # Brief pause for cancels to process
            await asyncio.sleep(0.03)
            self.tracker.clear()

            # PLACE new orders
            skew = self.inventory.skew_factor()
            is_too_long = self.inventory.is_too_long()
            is_too_short = self.inventory.is_too_short()

            quotes = self.spread.compute(self.latest_mid, skew, is_too_long, is_too_short)

            # Check if we actually have enough holdings to sell
            can_sell = not is_too_short and self.inventory.holdings >= quotes["ask_qty"] - 1e-8

            print(
                f"[MMBot] Requote: mid={self.latest_mid:.2f} skew={skew:.2f} "
                f"bid={quotes['bid_price']:.2f}x{quotes['bid_qty']:.4f} "
                f"ask={quotes['ask_price']:.2f}x{quotes['ask_qty']:.4f} "
                f"cancelled={len(old_ids)} can_sell={can_sell}"
            )

            if not is_too_long:
                await self.client.place_limit(
                    self.symbol,
                    "buy",
                    quotes["bid_price"],
                    quotes["bid_qty"],
                )
                self.tracker.register_sent("bid")

            if can_sell:
                await self.client.place_limit(
                    self.symbol,
                    "sell",
                    quotes["ask_price"],
                    quotes["ask_qty"],
                )
                self.tracker.register_sent("ask")

            self.last_mid_quoted = self.latest_mid

    def _check_pnl_floor(self):
        """Halt all trading if portfolio drops below the PnL floor."""
        if self._halted:
            return
        if self.inventory.total_val < PNL_FLOOR:
            self._halted = True
            print(
                f"[MMBot] ⚠ PNL FLOOR HIT — portfolio ${self.inventory.total_val:.2f} "
                f"< floor ${PNL_FLOOR:.2f}. Halting all new orders."
            )

    async def _handle_message(self, msg: dict):
        t = msg.get("type")

        if t == "welcome":
            self.client.user_id = msg.get("user_id")
            return

        if t == "portfolio":
            self.inventory.on_portfolio_update(msg)
            self.kpi.record_equity(msg["total_value"])
            self._check_pnl_floor()
            self._update_status()
            return

        if t == "open_orders":
            # Only process open_orders ONCE on initial connect
            if not self._initial_sync_done:
                self._initial_sync_done = True
                await self._on_open_orders(msg)
            return

        if t == "error":
            print(f"[MMBot] Exchange error: {msg.get('message')}")
            # Clear pending acks so the bot doesn't get stuck waiting
            # for an ack that will never come (e.g. rejected sell orders)
            self.tracker.clear_pending()
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
        my_orders = [o for o in orders if o.get("symbol") == self.symbol]

        if my_orders:
            self.tracker.clear()
            for o in my_orders:
                self.tracker.on_ack(o["order_id"])
            print(f"[MMBot] Synced {len(my_orders)} existing orders from open_orders")
        else:
            print("[MMBot] No existing orders to restore")

    def _reset_for_new_session(self):
        self.inventory = InventoryManager(symbol=self.symbol)
        self.tracker.clear()
        self.kpi = MMKPITracker()
        self.latest_mid = 0.0
        self.last_mid_quoted = 0.0
        self._halted = False
        self._initial_sync_done = False
        self._seed_order_sent = False
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
        status = self.kpi.get_status(self.inventory.total_val, self.inventory.holdings)
        status["halted"] = self._halted
        update_status(status)


async def main():
    bot = MarketMakerBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
