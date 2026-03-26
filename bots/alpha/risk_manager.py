from dataclasses import dataclass

from shared.config import (
    ALPHA_COOLDOWN_TICKS,
    ALPHA_RISK_PCT,
    ALPHA_STOP_PCT,
    ALPHA_TP_PCT,
    STARTING_EQUITY,
)


@dataclass
class Position:
    entry_price: float
    quantity: float
    stop_trigger: float
    tp_price: float
    tp_order_id: int | None
    side: str = "long"  # "long" or "short"


class RiskManager:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.equity: float = STARTING_EQUITY
        self.position: Position | None = None
        self.cooldown: int = 0
        self._server_holdings: float = 0.0
        self._server_avg_cost: float = 0.0
        self._server_unreal_pnl: float = 0.0

    def on_portfolio_update(self, msg: dict):
        self.equity = float(msg.get("total_value", self.equity))

        positions = msg.get("positions", {})
        my_pos = positions.get(self.symbol, {})
        self._server_holdings = float(my_pos.get("holdings", 0.0))
        self._server_avg_cost = float(my_pos.get("avg_cost", 0.0))
        self._server_unreal_pnl = float(my_pos.get("unrealized_pnl", 0.0))

    def tick(self):
        if self.cooldown > 0:
            self.cooldown -= 1

    def calculate_size(self, entry_price: float, confidence: float, daily_halted: bool) -> float:
        if self.position is not None:
            return 0.0
        if self.cooldown > 0:
            return 0.0
        if daily_halted:
            return 0.0

        risk_amount = self.equity * ALPHA_RISK_PCT
        stop_distance = entry_price * ALPHA_STOP_PCT
        if stop_distance <= 0:
            return 0.0

        base_size = risk_amount / stop_distance
        max_affordable = (self.equity * 0.20) / entry_price
        base_size = min(base_size, max_affordable)

        final_size = base_size * confidence

        if final_size < 0.001:
            return 0.0
        if final_size * entry_price > self.equity:
            return 0.0

        return round(final_size, 4)

    def open_position(self, entry_price: float, quantity: float,
                      tp_order_id: int | None, side: str = "long"):
        if side == "long":
            stop_trigger = float(entry_price) * (1.0 - ALPHA_STOP_PCT)
            tp_price = float(entry_price) * (1.0 + ALPHA_TP_PCT)
        else:
            stop_trigger = float(entry_price) * (1.0 + ALPHA_STOP_PCT)
            tp_price = float(entry_price) * (1.0 - ALPHA_TP_PCT)

        self.position = Position(
            entry_price=float(entry_price),
            quantity=float(quantity),
            stop_trigger=stop_trigger,
            tp_price=tp_price,
            tp_order_id=tp_order_id,
            side=side,
        )

    def close_position(self, exit_price: float, reason: str) -> float:
        if self.position is None:
            return 0.0

        if self.position.side == "long":
            pnl = (float(exit_price) - self.position.entry_price) * self.position.quantity
        else:
            pnl = (self.position.entry_price - float(exit_price)) * self.position.quantity

        print(f"[AlphaBot] Closed {self.position.side.upper()} | "
              f"entry={self.position.entry_price:.2f} exit={exit_price:.2f} "
              f"qty={self.position.quantity:.4f} pnl=${pnl:.2f} reason={reason}")

        self.cooldown = ALPHA_COOLDOWN_TICKS
        self.position = None
        return float(pnl)

    def should_stop_loss(self, current_price: float) -> bool:
        if self.position is None:
            return False
        if self.position.side == "long":
            return float(current_price) <= self.position.stop_trigger
        else:
            return float(current_price) >= self.position.stop_trigger

    def should_reverse_exit(self, decision: str, score: float) -> bool:
        if self.position is None:
            return False
        if self.position.side == "long":
            return decision == "SELL" and float(score) < -0.65
        else:
            return decision == "BUY" and float(score) > 0.65

    def on_take_profit_filled(self, fill_price: float) -> float:
        return self.close_position(fill_price, "TAKE_PROFIT")

    def is_flat(self) -> bool:
        return self.position is None

    def get_equity(self) -> float:
        return self.equity

    def get_position(self) -> Position | None:
        return self.position
