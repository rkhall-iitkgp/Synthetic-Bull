#pragma once

#include "Types.hpp"
#include <functional>
#include <vector>
#include <mutex>
#include <deque>

namespace sb {

// Called when a candle period closes
using CandleCallback = std::function<void(const Candle&)>;

class CandleAggregator {
public:
    explicit CandleAggregator(int period_ms = 1000, CandleCallback cb = nullptr);

    // Feed a trade into the current candle
    void addTrade(double price, double qty);

    // Feed a raw price tick (from GBM) — updates OHLC without adding volume
    void addPrice(double price);

    // Set / change the candle-close callback
    void setCallback(CandleCallback cb);

    // Get the last N completed candles (for replay to new clients)
    std::vector<Candle> getHistory(int count = 200) const;

private:
    void checkPeriod(uint64_t now_ms);
    void closeCandle();

    int           period_ms_;
    CandleCallback callback_;

    // Current open candle
    double   cur_open_   = 0.0;
    double   cur_high_   = 0.0;
    double   cur_low_    = 0.0;
    double   cur_close_  = 0.0;
    double   cur_volume_ = 0.0;
    uint64_t cur_start_  = 0;    // period start (ms)
    bool     has_data_   = false;

    // History ring — keep up to 1000 candles
    static constexpr int MAX_HISTORY = 1000;
    std::deque<Candle> history_;
    mutable std::mutex mutex_;
};

} // namespace sb
