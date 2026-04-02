from alpha.indicators import momentum_signal, order_book_imbalance, zscore_signal
from alpha.config import ALPHA_MOMENTUM_THRESH, ALPHA_ZSCORE_THRESH


class RegimeSignalProcessor:
    """Select strategy by regime, then apply OBI confirmation gate."""

    def process(self, regime: str, prices: list[float], bids: list, asks: list) -> dict:
        if regime == "random":
            return {"signal": 0.0, "decision": "HOLD", "obi_raw": 0.0, "regime": regime}

        if regime == "trending":
            raw = momentum_signal(prices)
            if raw > ALPHA_MOMENTUM_THRESH:
                candidate = "BUY"
            elif raw < -ALPHA_MOMENTUM_THRESH:
                candidate = "SELL"
            else:
                return {"signal": float(raw), "decision": "HOLD", "obi_raw": 0.0, "regime": regime}
        elif regime == "mean_reverting":
            z_val = zscore_signal(prices)
            raw = -z_val
            if z_val > ALPHA_ZSCORE_THRESH:
                candidate = "SELL"
            elif z_val < -ALPHA_ZSCORE_THRESH:
                candidate = "BUY"
            else:
                return {"signal": float(raw), "decision": "HOLD", "obi_raw": 0.0, "regime": regime}
        else:
            return {"signal": 0.0, "decision": "HOLD", "obi_raw": 0.0, "regime": "random"}

        obi = order_book_imbalance(bids, asks)
        if (candidate == "BUY" and obi <= 0) or (candidate == "SELL" and obi >= 0):
            return {"signal": float(raw), "decision": "HOLD", "obi_raw": float(obi), "regime": regime}

        return {
            "signal": float(raw),
            "decision": candidate,
            "obi_raw": float(obi),
            "regime": regime,
        }
