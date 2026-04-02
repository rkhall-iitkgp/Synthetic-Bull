from alpha.config import ALPHA_DAILY_DRAWDOWN

TICKS_PER_DAY = 86_400


class DrawdownGuard:
    def __init__(self, starting_equity: float):
        self._starting_equity = float(starting_equity)
        self._day_start_equity = float(starting_equity)
        self._ticks_today = 0
        self._halted = False

    def _start_new_day(self, equity: float):
        self._day_start_equity = float(equity)
        self._ticks_today = 0
        self._halted = False

    def tick(self, current_equity: float) -> bool:
        self._ticks_today += 1
        if self._ticks_today >= TICKS_PER_DAY:
            self._start_new_day(current_equity)

        if self._halted:
            return False

        if self.current_drawdown(current_equity) >= ALPHA_DAILY_DRAWDOWN:
            self._halted = True
            return True

        return False

    def is_halted(self) -> bool:
        return self._halted

    def current_drawdown(self, current_equity: float) -> float:
        base = self._day_start_equity if self._day_start_equity > 0 else self._starting_equity
        if base <= 0:
            return 0.0
        dd = (base - float(current_equity)) / base
        return max(0.0, min(1.0, dd))
