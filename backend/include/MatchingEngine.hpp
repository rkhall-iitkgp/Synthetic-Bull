#pragma once

#include "OrderBook.hpp"
#include <mutex>
#include <functional>
#include <atomic>
#include <vector>

namespace sb {

// Called for every fill, outside the engine mutex
using TradeCallback = std::function<void(const Trade&)>;

class MatchingEngine {
public:
    explicit MatchingEngine(TradeCallback cb = nullptr);

    // Submit an order.  The order's .id and .timestamp are assigned by the engine.
    // Returns the number of fills that occurred.
    int processOrder(Order& order);

    // Cancel a resting order by ID.  Returns true if found and removed.
    bool cancelOrder(uint64_t order_id);

    // Cancel only if the order exists and is owned by user_id.
    bool cancelOrderForUser(uint64_t order_id, const std::string& user_id);

    // Thread-safe snapshot of the order book
    OrderBookSnapshot getSnapshot(int depth = 20) const;

    // Set / change the trade callback
    void setTradeCallback(TradeCallback cb);

    // Current trade counter (for trade IDs)
    uint64_t tradeCount() const { return trade_counter_.load(); }

private:
    void matchLimit(Order& order, std::vector<Trade>& trades);
    void matchMarket(Order& order, std::vector<Trade>& trades);

    OrderBook     book_;
    mutable std::mutex  mutex_;
    TradeCallback trade_cb_;

    std::atomic<uint64_t> order_counter_{0};
    std::atomic<uint64_t> trade_counter_{0};
};

} // namespace sb
