from shared.config import MM_BASE_SPREAD_PCT, MM_INVENTORY_SKEW, MM_QUOTE_QTY


class SpreadCalculator:
    def compute(self, mid: float, skew: float, is_too_long: bool, is_too_short: bool) -> dict:
        bid_offset = MM_BASE_SPREAD_PCT * (1.0 + skew * MM_INVENTORY_SKEW)
        ask_offset = MM_BASE_SPREAD_PCT * (1.0 - skew * MM_INVENTORY_SKEW)

        bid_price = float(mid) * (1.0 - bid_offset)
        ask_price = float(mid) * (1.0 + ask_offset)

        if is_too_long:
            bid_qty = MM_QUOTE_QTY * 0.5
            ask_qty = MM_QUOTE_QTY
        elif is_too_short:
            bid_qty = MM_QUOTE_QTY
            ask_qty = MM_QUOTE_QTY * 0.5
        else:
            bid_qty = MM_QUOTE_QTY
            ask_qty = MM_QUOTE_QTY

        return {
            "bid_price": round(bid_price, 2),
            "ask_price": round(ask_price, 2),
            "bid_qty": round(bid_qty, 4),
            "ask_qty": round(ask_qty, 4),
        }
