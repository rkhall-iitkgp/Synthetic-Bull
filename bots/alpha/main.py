"""
Alpha Bot - main event loop.

Run with:
    python -m alpha.main

Key profitability improvements:
  - Warmup gate: blocks signals until 100 candles buffered
  - PnL floor halt at $80k
  - 15-second post-trade cooldown
  - 20% hard position cap per trade
  - Regime-adaptive strategy with Hurst + OBI + ATR sizing
  - Cancel-all on reconnect
"""

import asyncio
import threading
import time

from alpha.drawdown_guard import DrawdownGuard
from alpha.indicators import compute_hurst
from alpha.kpi_tracker import KPITracker
from alpha.risk_manager import RiskManager
from alpha.signal_scorer import RegimeSignalProcessor
from alpha.status_server import run as run_status_server
from alpha.status_server import update_status
from alpha.tick_buffer import TickBuffer
from shared.config import (
    ALPHA_BOT_API_KEY,
    ALPHA_HURST_MR,
    ALPHA_HURST_TRENDING,
    ALPHA_HURST_WINDOW,
    ALPHA_STOP_PCT,
    ALPHA_SYMBOL,
    ALPHA_TP_PCT,
    STARTING_EQUITY,
)
from shared.exchange_client import ExchangeClient


class AlphaBot:
    def __init__(self):
        self.symbol: str = ALPHA_SYMBOL
        self.client = ExchangeClient(
            on_message=self._handle_message,
            on_reconnect=self._on_reconnect,
            api_key=ALPHA_BOT_API_KEY,
        )
        self.buffer = TickBuffer()
        self.scorer = RegimeSignalProcessor()
        self.risk = RiskManager(symbol=ALPHA_SYMBOL)
        self.drawdown = DrawdownGuard(STARTING_EQUITY)
        self.kpi = KPITracker()
        self.pending_tp_order_id: int | None = None
        self.latest_mid: float = 0.0
        self.latest_bids: list = []
        self.latest_asks: list = []
        self._regime: str = "random"
        self._regime_lock = threading.Lock()

        self._initial_replay_done = True
        self._waiting_for_entry_ack = False
        self._waiting_for_tp_ack = False
        self._pending_entry_qty: float = 0.0
        self._pending_entry_price: float = 0.0
        self._pending_entry_side: str = "long"
        self._candle_count: int = 0
        self._warmup_logged: bool = False
        self._initial_sync_done: bool = False

    async def run(self):
        hurst_thread = threading.Thread(
            target=self._hurst_worker,
            daemon=True,
            name="hurst-worker",
        )
        hurst_thread.start()

        await asyncio.gather(
            self.client.run(),
            run_status_server(),
        )

    def _hurst_worker(self):
        while True:
            time.sleep(2.0)
            prices = self.buffer.get()
            if len(prices) < ALPHA_HURST_WINDOW:
                continue

            hurst = compute_hurst(prices[-ALPHA_HURST_WINDOW:])
            if hurst > ALPHA_HURST_TRENDING:
                new_regime = "trending"
            elif hurst < ALPHA_HURST_MR:
                new_regime = "mean_reverting"
            else:
                new_regime = "random"

            with self._regime_lock:
                if self._regime != new_regime:
                    print(f"[AlphaBot] Regime: {self._regime} -> {new_regime} (H={hurst:.3f})")
                self._regime = new_regime

    async def _on_reconnect(self):
        """Cancel all known orders on reconnect."""
        print("[AlphaBot] Reconnect detected - cancelling TP order if any")
        if self.pending_tp_order_id is not None:
            await self.client.cancel(self.symbol, self.pending_tp_order_id)
            self.pending_tp_order_id = None
        self._waiting_for_entry_ack = False
        self._waiting_for_tp_ack = False

    async def _handle_message(self, msg: dict):
        t = msg.get("type")

        if t == "welcome":
            self.client.user_id = msg.get("user_id")
            self._initial_replay_done = True
            return

        if t == "portfolio":
            self.risk.on_portfolio_update(msg)
            return

        if t == "open_orders":
            if not self._initial_sync_done:
                self._initial_sync_done = True
                await self._on_open_orders(msg)
            return

        if t == "error":
            print(f"[AlphaBot] Exchange error: {msg.get('message')}")
            return

        if t == "pong":
            return

        if msg.get("symbol") != self.symbol:
            return

        if t == "candle":
            await self._on_candle(msg)

        elif t == "orderbook":
            self.latest_mid = float(msg.get("mid", self.latest_mid))
            self.latest_bids = msg.get("bids", [])
            self.latest_asks = msg.get("asks", [])
            await self._check_stop_loss()
            self._update_status()

        elif t == "trade":
            await self._on_trade(msg)

        elif t == "ack":
            await self._on_ack(msg)

        elif t == "cancel_ack":
            pass

    async def _on_open_orders(self, msg: dict):
        orders = msg.get("orders", [])
        for o in orders:
            if o.get("symbol") != self.symbol:
                continue
            if self.pending_tp_order_id is None:
                if o.get("side") == "sell" or o.get("side") == "buy":
                    self.pending_tp_order_id = o["order_id"]
                    print(
                        f"[AlphaBot] Restored TP order {o['order_id']} "
                        f"{o['side']} @ {o['price']} from open_orders"
                    )

    def _reset_for_new_session(self):
        self.buffer = TickBuffer()
        self.risk = RiskManager(symbol=self.symbol)
        self.drawdown = DrawdownGuard(STARTING_EQUITY)
        self.kpi = KPITracker()
        self.pending_tp_order_id = None
        self.latest_mid = 0.0
        self.latest_bids = []
        self.latest_asks = []
        with self._regime_lock:
            self._regime = "random"
        self._initial_replay_done = True
        self._waiting_for_entry_ack = False
        self._waiting_for_tp_ack = False
        self._pending_entry_qty = 0.0
        self._pending_entry_price = 0.0
        self._pending_entry_side = "long"
        self._candle_count = 0
        self._warmup_logged = False
        self._initial_sync_done = False
        self._update_status()

    async def _on_candle(self, msg: dict):
        close_price = float(msg["c"])
        self.buffer.add(close_price)

        if not self._initial_replay_done:
            return

        self.risk.tick()
        self._candle_count += 1

        # WARMUP GATE: block all signals until we have enough data
        if not self.buffer.is_ready():
            if not self._warmup_logged and self._candle_count % 20 == 0:
                print(f"[AlphaBot] Warming up: {self.buffer.size()}/100 candles")
            return

        if not self._warmup_logged:
            self._warmup_logged = True
            print(f"[AlphaBot] Warmup complete - {self.buffer.size()} candles buffered, signals active")

        total_val = self.risk.get_equity()
        circuit_fired = self.drawdown.tick(total_val)
        if circuit_fired:
            await self._emergency_exit("CIRCUIT_BREAKER")
            return

        # PnL floor check
        if self.risk.is_pnl_floor_hit():
            if not self.risk.is_flat():
                await self._emergency_exit("PNL_FLOOR")
            self._update_status()
            return

        if not self.risk.is_flat():
            await self._check_signal_reversal(close_price)
            self._update_status()
            return

        if not self.drawdown.is_halted():
            await self._check_entry(close_price)

        self._update_status()

    async def _cancel_tp_if_any(self):
        if self.pending_tp_order_id is not None:
            await self.client.cancel(self.symbol, self.pending_tp_order_id)
            self.pending_tp_order_id = None

    async def _check_stop_loss(self):
        if self.risk.is_flat():
            return
        if not self.risk.should_stop_loss(self.latest_mid):
            return

        position = self.risk.get_position()
        if position is None:
            return

        await self._cancel_tp_if_any()

        if position.side == "long":
            await self.client.place_market(self.symbol, "sell", position.quantity)
        else:
            await self.client.place_market(self.symbol, "buy", position.quantity)

        self.risk.close_position(self.latest_mid, "STOP_LOSS")
        self.kpi.record_trade(
            position.entry_price,
            self.latest_mid,
            position.quantity,
            "STOP_LOSS",
            self.risk.get_equity(),
            side=position.side,
        )

    async def _check_signal_reversal(self, price: float):
        if not self.buffer.is_ready():
            return

        prices = self.buffer.get()
        with self._regime_lock:
            regime = self._regime

        signal = self.scorer.process(regime, prices, self.latest_bids, self.latest_asks)
        if not self.risk.should_reverse_exit(signal["decision"], signal["signal"]):
            return

        position = self.risk.get_position()
        if position is None:
            return

        await self._cancel_tp_if_any()

        if position.side == "long":
            await self.client.place_market(self.symbol, "sell", position.quantity)
        else:
            await self.client.place_market(self.symbol, "buy", position.quantity)

        self.risk.close_position(price, "SIGNAL_REVERSAL")
        self.kpi.record_trade(
            position.entry_price,
            price,
            position.quantity,
            "SIGNAL_REVERSAL",
            self.risk.get_equity(),
            side=position.side,
        )

    async def _check_entry(self, price: float):
        prices = self.buffer.get()
        with self._regime_lock:
            regime = self._regime

        signal = self.scorer.process(regime, prices, self.latest_bids, self.latest_asks)

        # Debug logging every 10 candles
        if self._candle_count % 10 == 0:
            print(
                f"[AlphaBot] {self.symbol} regime={regime} signal={signal['signal']:.3f} "
                f"decision={signal['decision']} obi={signal['obi_raw']:.3f} "
                f"cooldown={self.risk.cooldown} mid={price:.2f}"
            )

        if signal["decision"] == "BUY":
            qty = self.risk.calculate_size(
                price,
                signal["signal"],
                self.drawdown.is_halted(),
                prices,
            )
            if qty <= 0:
                return

            print(
                f"[AlphaBot] LONG entry | regime={regime} "
                f"signal={signal['signal']:.3f} qty={qty:.4f} @ ~{price:.2f}"
            )
            await self.client.place_market(self.symbol, "buy", qty)
            self._waiting_for_entry_ack = True
            self._pending_entry_qty = qty
            self._pending_entry_price = price
            self._pending_entry_side = "long"

        elif signal["decision"] == "SELL":
            qty = self.risk.calculate_size(
                price,
                signal["signal"],
                self.drawdown.is_halted(),
                prices,
            )
            if qty <= 0:
                return

            print(
                f"[AlphaBot] SHORT entry | regime={regime} "
                f"signal={signal['signal']:.3f} qty={qty:.4f} @ ~{price:.2f}"
            )
            await self.client.place_market(self.symbol, "sell", qty)
            self._waiting_for_entry_ack = True
            self._pending_entry_qty = qty
            self._pending_entry_price = price
            self._pending_entry_side = "short"

    async def _on_ack(self, msg: dict):
        fills = int(msg.get("fills", 0))
        order_id = int(msg["order_id"])

        if self._waiting_for_entry_ack and fills > 0:
            self._waiting_for_entry_ack = False
            self._waiting_for_tp_ack = True
            entry_price = self.latest_mid if self.latest_mid > 0 else self._pending_entry_price
            self._pending_entry_price = entry_price

            # Place take-profit in the opposite direction
            if self._pending_entry_side == "long":
                tp_price = entry_price * (1.0 + ALPHA_TP_PCT)
                await self.client.place_limit(self.symbol, "sell", tp_price, self._pending_entry_qty)
            else:
                tp_price = entry_price * (1.0 - ALPHA_TP_PCT)
                await self.client.place_limit(self.symbol, "buy", tp_price, self._pending_entry_qty)
            return

        if self._waiting_for_tp_ack:
            self._waiting_for_tp_ack = False
            self.pending_tp_order_id = order_id
            self.risk.open_position(
                self._pending_entry_price,
                self._pending_entry_qty,
                self.pending_tp_order_id,
                side=self._pending_entry_side,
            )
            print(
                f"[AlphaBot] Position opened: {self._pending_entry_side.upper()} "
                f"qty={self._pending_entry_qty:.4f} @ {self._pending_entry_price:.2f} "
                f"TP order={self.pending_tp_order_id}"
            )
            self._pending_entry_qty = 0.0
            self._pending_entry_price = 0.0

    async def _on_trade(self, msg: dict):
        if self.pending_tp_order_id is None or self.client.user_id is None:
            return

        position = self.risk.get_position()
        if position is None:
            self.pending_tp_order_id = None
            return

        # Detect our TP fill
        if position.side == "long":
            if msg.get("seller") != self.client.user_id:
                return
        else:
            if msg.get("buyer") != self.client.user_id:
                return

        fill_price = float(msg["price"])
        self.risk.on_take_profit_filled(fill_price)
        self.kpi.record_trade(
            position.entry_price,
            fill_price,
            position.quantity,
            "TAKE_PROFIT",
            self.risk.get_equity(),
            side=position.side,
        )
        self.pending_tp_order_id = None

    async def _emergency_exit(self, reason: str):
        if self.risk.is_flat():
            return

        position = self.risk.get_position()
        if position is None:
            return

        await self._cancel_tp_if_any()

        if position.side == "long":
            await self.client.place_market(self.symbol, "sell", position.quantity)
        else:
            await self.client.place_market(self.symbol, "buy", position.quantity)

        exit_price = self.latest_mid if self.latest_mid > 0 else position.entry_price
        self.risk.close_position(exit_price, reason)
        self.kpi.record_trade(
            position.entry_price,
            exit_price,
            position.quantity,
            reason,
            self.risk.get_equity(),
            side=position.side,
        )

    def _total_value(self) -> float:
        return self.risk.get_equity()

    def _update_status(self):
        pos = "FLAT"
        position = self.risk.get_position()
        if position:
            pos = position.side.upper()
        status = self.kpi.get_status(self.risk.get_equity(), pos)
        status["halted"] = self.risk.is_pnl_floor_hit() or self.drawdown.is_halted()
        with self._regime_lock:
            status["regime"] = self._regime
        update_status(status)


async def main():
    bot = AlphaBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
