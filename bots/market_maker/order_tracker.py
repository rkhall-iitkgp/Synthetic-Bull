from collections import deque


class OrderTracker:
    """
    The MM bot keeps at most 2 active resting orders at any time:
    one bid and one ask. On each requote cycle it cancels both and
    places new ones.
    """

    def __init__(self):
        self._active: dict[int, str] = {}
        self._pending_acks: int = 0
        self._sent_sides: deque[str] = deque()

    def on_ack(self, order_id: int):
        side = self._sent_sides.popleft() if self._sent_sides else "pending"
        self._active[order_id] = side
        self._pending_acks = max(0, self._pending_acks - 1)

    def on_cancel_ack(self, order_id: int):
        self._active.pop(order_id, None)

    def on_fill(self, order_id: int):
        self._active.pop(order_id, None)

    def register_sent(self, side: str):
        self._pending_acks += 1
        self._sent_sides.append(side)

    def get_all_ids(self) -> list[int]:
        return list(self._active.keys())

    def has_pending(self) -> bool:
        return self._pending_acks > 0

    def count(self) -> int:
        return len(self._active)

    def clear(self):
        self._active.clear()
        self._pending_acks = 0
        self._sent_sides.clear()
