import numpy as np

from shared.config import BB_PERIOD, EMA_LONG, EMA_SHORT, MACD_SIGNAL, RSI_PERIOD


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1)
    out = np.zeros_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1.0 - k)
    return out


def ema_vote(prices: list[float]) -> float:
    if len(prices) < EMA_LONG:
        return 0.0
    arr = np.asarray(prices, dtype=float)
    ema_short = _ema(arr, EMA_SHORT)
    ema_long = _ema(arr, EMA_LONG)
    gap = float(ema_short[-1] - ema_long[-1])
    return 1.0 if gap > 0 else -1.0


def rsi_vote(prices: list[float]) -> float:
    """RSI with configurable period (default 50 for 1-second candles).
    Longer period smooths out the noise that makes RSI-14 useless on fast data.
    """
    if len(prices) < RSI_PERIOD + 1:
        return 0.0

    arr = np.asarray(prices, dtype=float)
    changes = np.diff(arr)
    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)

    avg_gain = float(np.mean(gains[:RSI_PERIOD]))
    avg_loss = float(np.mean(losses[:RSI_PERIOD]))

    for i in range(RSI_PERIOD, len(changes)):
        avg_gain = avg_gain * ((RSI_PERIOD - 1) / RSI_PERIOD) + gains[i] * (1 / RSI_PERIOD)
        avg_loss = avg_loss * ((RSI_PERIOD - 1) / RSI_PERIOD) + losses[i] * (1 / RSI_PERIOD)

    if avg_loss == 0.0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    vote = (50.0 - rsi) / 50.0
    return _clamp(float(vote))


def price_deviation_vote(prices: list[float]) -> float:
    """Price deviation from slow EMA — a mean-reversion signal.
    When price is far above the slow EMA, vote sell; far below, vote buy.
    This replaces the noisy RSI-14 with a more stable signal.
    """
    slow_period = 100
    if len(prices) < slow_period:
        return 0.0

    arr = np.asarray(prices, dtype=float)
    slow_ema = _ema(arr, slow_period)
    current = float(arr[-1])
    ema_val = float(slow_ema[-1])

    if ema_val == 0.0:
        return 0.0

    # Percentage deviation from slow EMA
    deviation = (current - ema_val) / ema_val

    # Scale: 1% deviation => full vote
    vote = -deviation / 0.01
    return _clamp(float(vote))


def macd_vote(prices: list[float]) -> float:
    if len(prices) < EMA_LONG + MACD_SIGNAL:
        return 0.0

    arr = np.asarray(prices, dtype=float)
    ema12 = _ema(arr, EMA_SHORT)
    ema26 = _ema(arr, EMA_LONG)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, MACD_SIGNAL)
    histogram = float(macd_line[-1] - signal_line[-1])

    sign = 1.0 if histogram > 0 else -1.0
    vote = sign * min(abs(histogram) / 0.5, 1.0)
    return _clamp(float(vote))


def bollinger_vote(prices: list[float]) -> float:
    if len(prices) < BB_PERIOD:
        return 0.0

    window = np.asarray(prices[-BB_PERIOD:], dtype=float)
    sma = float(np.mean(window))
    std = float(np.std(window, ddof=0))

    if std == 0.0:
        return 0.0

    upper = sma + 2.0 * std
    lower = sma - 2.0 * std
    pct_b = (window[-1] - lower) / (upper - lower)
    vote = (0.5 - pct_b) * 2.0
    return _clamp(float(vote))


class IndicatorEngine:
    def compute(self, prices: list[float]) -> dict:
        return {
            "ema": ema_vote(prices),
            "rsi": rsi_vote(prices),
            "macd": macd_vote(prices),
            "bollinger": bollinger_vote(prices),
            "price_deviation": price_deviation_vote(prices),
        }
