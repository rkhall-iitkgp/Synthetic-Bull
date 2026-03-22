#include "CandleAggregator.hpp"
#include <algorithm>

namespace sb {

CandleAggregator::CandleAggregator(int period_ms, CandleCallback cb)
    : period_ms_(period_ms), callback_(std::move(cb)) {}

void CandleAggregator::setCallback(CandleCallback cb) {
    std::lock_guard<std::mutex> lock(mutex_);
    callback_ = std::move(cb);
}

// ─── addTrade ────────────────────────────────────────────────────────────────

void CandleAggregator::addTrade(double price, double qty) {
    std::lock_guard<std::mutex> lock(mutex_);
    uint64_t now = now_ms();
    checkPeriod(now);

    if (!has_data_) {
        cur_open_  = price;
        cur_high_  = price;
        cur_low_   = price;
        cur_close_ = price;
        has_data_  = true;
    } else {
        cur_high_  = std::max(cur_high_, price);
        cur_low_   = std::min(cur_low_, price);
        cur_close_ = price;
    }
    cur_volume_ += qty;
}

// ─── addPrice ────────────────────────────────────────────────────────────────

void CandleAggregator::addPrice(double price) {
    std::lock_guard<std::mutex> lock(mutex_);
    uint64_t now = now_ms();
    checkPeriod(now);

    if (!has_data_) {
        cur_open_  = price;
        cur_high_  = price;
        cur_low_   = price;
        cur_close_ = price;
        has_data_  = true;
    } else {
        cur_high_  = std::max(cur_high_, price);
        cur_low_   = std::min(cur_low_, price);
        cur_close_ = price;
    }
}

// ─── getHistory ──────────────────────────────────────────────────────────────

std::vector<Candle> CandleAggregator::getHistory(int count) const {
    std::lock_guard<std::mutex> lock(mutex_);
    int n = std::min(count, static_cast<int>(history_.size()));
    return std::vector<Candle>(history_.end() - n, history_.end());
}

// ─── checkPeriod ─────────────────────────────────────────────────────────────
// If we've crossed a period boundary, close the current candle.

void CandleAggregator::checkPeriod(uint64_t now) {
    if (cur_start_ == 0) {
        // First data point — align to period boundary
        cur_start_ = (now / period_ms_) * period_ms_;
        return;
    }

    uint64_t period_end = cur_start_ + static_cast<uint64_t>(period_ms_);
    while (now >= period_end) {
        closeCandle();
        cur_start_ = period_end;
        period_end = cur_start_ + static_cast<uint64_t>(period_ms_);
    }
}

// ─── closeCandle ─────────────────────────────────────────────────────────────

void CandleAggregator::closeCandle() {
    if (!has_data_) return;

    Candle c;
    c.open      = cur_open_;
    c.high      = cur_high_;
    c.low       = cur_low_;
    c.close     = cur_close_;
    c.volume    = cur_volume_;
    c.timestamp = cur_start_;

    history_.push_back(c);
    while (static_cast<int>(history_.size()) > MAX_HISTORY) {
        history_.pop_front();
    }

    // Fire callback (still under mutex — but the callback typically just
    // defers to the uWS loop, which is fast and non-blocking)
    if (callback_) {
        callback_(c);
    }

    // Reset for next period — carry close forward as new open
    cur_open_   = cur_close_;
    cur_high_   = cur_close_;
    cur_low_    = cur_close_;
    cur_volume_ = 0.0;
    // has_data_ stays true so the carry-forward works
}

} // namespace sb
