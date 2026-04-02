from market_maker.config import MM_BASE_SPREAD_PCT, MM_INVENTORY_SKEW, MM_MAX_INVENTORY, MM_QUOTE_QTY


class SpreadCalculator:
    def compute(self, mid: float, skew: float, is_too_long: bool, is_too_short: bool) -> dict:
        abs_skew = abs(skew)

        # Aggressively WIDEN the spread when inventory exceeds 50% of max
        # This ensures the bot mean-reverts instead of drifting
        if abs_skew > 0.5:
            inventory_widen = 1.0 + (abs_skew - 0.5) * 4.0  # up to 3x wider at max
        else:
            inventory_widen = 1.0

        base_spread = MM_BASE_SPREAD_PCT * inventory_widen

        # Shift (skew) + widen
        bid_offset = base_spread * (1.0 + skew * MM_INVENTORY_SKEW)
        ask_offset = base_spread * (1.0 - skew * MM_INVENTORY_SKEW)

        # Ensure offsets never go negative (would cross the spread)
        bid_offset = max(bid_offset, MM_BASE_SPREAD_PCT * 0.3)
        ask_offset = max(ask_offset, MM_BASE_SPREAD_PCT * 0.3)

        bid_price = float(mid) * (1.0 - bid_offset)
        ask_price = float(mid) * (1.0 + ask_offset)

        if is_too_long:
            bid_qty = MM_QUOTE_QTY * 0.25  # barely buy
            ask_qty = MM_QUOTE_QTY * 1.5   # aggressively sell
        elif is_too_short:
            bid_qty = MM_QUOTE_QTY * 1.5   # aggressively buy
            ask_qty = MM_QUOTE_QTY * 0.25  # barely sell
        else:
            bid_qty = MM_QUOTE_QTY
            ask_qty = MM_QUOTE_QTY

        return {
            "bid_price": round(bid_price, 2),
            "ask_price": round(ask_price, 2),
            "bid_qty": round(bid_qty, 4),
            "ask_qty": round(ask_qty, 4),
        }
