from shared.config import MM_MAX_INVENTORY, STARTING_EQUITY


class InventoryManager:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.holdings: float = 0.0
        self.avg_cost: float = 0.0
        self.cash: float = STARTING_EQUITY
        self.total_val: float = STARTING_EQUITY

    def on_portfolio_update(self, msg: dict):
        self.cash = float(msg.get("cash", self.cash))
        self.total_val = float(msg.get("total_value", self.total_val))

        positions = msg.get("positions", {})
        my_pos = positions.get(self.symbol, {})

        self.holdings = float(my_pos.get("holdings", 0.0))
        self.avg_cost = float(my_pos.get("avg_cost", 0.0))

    def skew_factor(self) -> float:
        if MM_MAX_INVENTORY == 0:
            return 0.0
        skew = self.holdings / MM_MAX_INVENTORY
        return max(-1.0, min(1.0, float(skew)))

    def is_too_long(self) -> bool:
        return self.holdings >= MM_MAX_INVENTORY

    def is_too_short(self) -> bool:
        return self.holdings <= -MM_MAX_INVENTORY

    def unrealized_pnl(self, mid_price: float) -> float:
        if self.holdings == 0:
            return 0.0
        return (float(mid_price) - self.avg_cost) * self.holdings
