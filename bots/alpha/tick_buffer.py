from collections import deque

from alpha.config import ALPHA_MIN_TICKS, ALPHA_PRICE_WINDOW


class TickBuffer:
    def __init__(self):
        self._prices: deque[float] = deque(maxlen=ALPHA_PRICE_WINDOW)

    def add(self, price: float) -> None:
        self._prices.append(float(price))

    def get(self) -> list[float]:
        return list(self._prices)

    def latest(self) -> float | None:
        if not self._prices:
            return None
        return self._prices[-1]

    def is_ready(self) -> bool:
        return len(self._prices) >= ALPHA_MIN_TICKS

    def size(self) -> int:
        return len(self._prices)
