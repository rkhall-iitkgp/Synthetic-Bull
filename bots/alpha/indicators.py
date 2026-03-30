import numpy as np


def compute_hurst(prices: list[float], max_lag: int = 20) -> float:
    """Compute Hurst exponent via R/S analysis."""
    if len(prices) < 10:
        return 0.5

    ts = np.array(prices, dtype=float)
    lags = range(2, max_lag)
    rs_values = []
    valid_lags = []

    for lag in lags:
        segments = [ts[i : i + lag] for i in range(0, len(ts) - lag, lag)]
        rs_list = []

        for seg in segments:
            mean = np.mean(seg)
            cumdev = np.cumsum(seg - mean)
            r_val = cumdev.max() - cumdev.min()
            s_val = np.std(seg, ddof=1)
            if s_val > 0:
                rs_list.append(r_val / s_val)

        if rs_list:
            rs_values.append(np.mean(rs_list))
            valid_lags.append(lag)

    if len(rs_values) < 2:
        return 0.5

    log_lags = np.log(valid_lags)
    log_rs = np.log(rs_values)
    h_val = np.polyfit(log_lags, log_rs, 1)[0]
    return float(np.clip(h_val, 0.0, 1.0))


def momentum_signal(prices: list[float], lookback: int = 20) -> float:
    """Compute volatility-normalized momentum score."""
    if len(prices) < lookback + 1:
        return 0.0

    returns = np.diff(np.log(np.array(prices[-(lookback + 1):], dtype=float)))
    total_return = float(np.sum(returns))
    vol = float(np.std(returns) * np.sqrt(lookback)) + 1e-9
    return total_return / vol


def zscore_signal(prices: list[float], lookback: int = 30) -> float:
    """Compute rolling-window z-score of latest price."""
    if len(prices) < lookback:
        return 0.0

    window = np.array(prices[-lookback:], dtype=float)
    mean = float(np.mean(window))
    std = float(np.std(window)) + 1e-9
    return float((window[-1] - mean) / std)


def _extract_qty(level) -> float:
    # Backend sends [price, qty, order_count] arrays.
    if isinstance(level, dict):
        return float(level.get("qty", level.get("quantity", 0.0)))
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[1])
    return 0.0


def order_book_imbalance(bids: list, asks: list, levels: int = 5) -> float:
    """Compute OBI over top book levels in [-1, 1]."""
    bid_volume = sum(_extract_qty(level) for level in bids[:levels])
    ask_volume = sum(_extract_qty(level) for level in asks[:levels])
    total = bid_volume + ask_volume
    if total <= 0.0:
        return 0.0
    return float((bid_volume - ask_volume) / total)


def compute_atr(prices: list[float], period: int = 14) -> float:
    """Compute ATR-like average absolute tick move from close prices."""
    if len(prices) < period + 1:
        return 0.0

    recent = prices[-(period + 1):]
    moves = [abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))]
    return float(np.mean(moves)) + 1e-9
