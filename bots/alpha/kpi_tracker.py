from dataclasses import dataclass

import numpy as np

from alpha.config import STARTING_EQUITY


@dataclass
class TradeRecord:
    entry: float
    exit: float
    qty: float
    reason: str
    pnl: float
    pct_return: float
    side: str = "long"


class KPITracker:
    def __init__(self):
        self._trades: list[TradeRecord] = []
        self._equity_curve: list[float] = [STARTING_EQUITY]
        self._realized_pnl: float = 0.0

    def record_trade(self, entry, exit_price, qty, reason, new_equity, side: str = "long"):
        entry = float(entry)
        exit_price = float(exit_price)
        qty = float(qty)
        if side == "long":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty
        pct_return = 0.0 if entry == 0 else (exit_price - entry) / entry
        self._trades.append(
            TradeRecord(
                entry=entry,
                exit=exit_price,
                qty=qty,
                reason=str(reason),
                pnl=float(pnl),
                pct_return=float(pct_return),
                side=side,
            )
        )
        self._realized_pnl += float(pnl)
        self._equity_curve.append(float(new_equity))

    def total_trades(self) -> int:
        return len(self._trades)

    def total_pnl(self) -> float:
        return float(sum(t.pnl for t in self._trades))

    def realized_pnl(self) -> float:
        return self._realized_pnl

    def win_rate(self) -> float:
        if not self._trades:
            return 0.0
        wins = sum(1 for t in self._trades if t.pnl > 0)
        return wins / len(self._trades)

    def sharpe_ratio(self) -> float:
        if len(self._trades) < 2:
            return 0.0
        returns = np.asarray([t.pct_return for t in self._trades], dtype=float)
        std = float(np.std(returns, ddof=1))
        if std == 0.0:
            return 0.0
        mean = float(np.mean(returns))
        return float((mean / std) * np.sqrt(len(returns)))

    def max_drawdown(self) -> float:
        peak = self._equity_curve[0]
        max_dd = 0.0
        for val in self._equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak
                if dd > max_dd:
                    max_dd = dd
        return float(max_dd)

    def get_status(self, current_equity: float, position: str) -> dict:
        unrealized = float(current_equity) - STARTING_EQUITY - self._realized_pnl
        return {
            "equity": round(float(current_equity), 2),
            "pnl": round(float(current_equity) - STARTING_EQUITY, 2),
            "realizedPnl": round(self._realized_pnl, 2),
            "unrealizedPnl": round(unrealized, 2),
            "position": position,
            "trades": self.total_trades(),
            "winRate": self.win_rate(),
            "sharpe": self.sharpe_ratio(),
            "maxDrawdown": self.max_drawdown(),
        }
