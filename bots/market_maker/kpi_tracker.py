from shared.config import STARTING_EQUITY


class MMKPITracker:
    def __init__(self):
        self.total_fills: int = 0
        self.total_spread_pnl: float = 0.0
        self.bid_fills: int = 0
        self.ask_fills: int = 0
        self.equity_curve: list[float] = [STARTING_EQUITY]
        self._peak: float = STARTING_EQUITY

    def on_fill(self, side: str, fill_price: float, qty: float, spread_captured: float):
        self.total_fills += 1
        if side == "bid":
            self.bid_fills += 1
        else:
            self.ask_fills += 1
        self.total_spread_pnl += float(spread_captured)

    def record_equity(self, equity: float):
        self.equity_curve.append(float(equity))
        if equity > self._peak:
            self._peak = float(equity)

    def max_drawdown(self) -> float:
        peak = self.equity_curve[0]
        max_dd = 0.0
        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
        return float(max_dd)

    def fill_rate_balance(self) -> float:
        if self.total_fills == 0:
            return 0.5
        return self.bid_fills / self.total_fills

    def get_status(self, current_equity: float, holdings: float) -> dict:
        return {
            "equity": round(float(current_equity), 2),
            "pnl": round(float(current_equity) - STARTING_EQUITY, 2),
            "position": "LONG"
            if holdings > 0.001
            else "SHORT"
            if holdings < -0.001
            else "FLAT",
            "holdings": round(float(holdings), 4),
            "totalFills": self.total_fills,
            "bidFills": self.bid_fills,
            "askFills": self.ask_fills,
            "fillBalance": round(self.fill_rate_balance(), 4),
            "maxDrawdown": self.max_drawdown(),
        }
