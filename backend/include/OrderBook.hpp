#pragma once

#include "Types.hpp"
#include <map>
#include <deque>
#include <unordered_map>
#include <optional>
#include <functional>

namespace sb {

// Location of an order inside the book (for O(log N) cancel)
struct OrderLocation {
    Side   side;
    double price;
};

class OrderBook {
public:
    // Insert an order at its price level
    void add(const Order& order);

    // Cancel an order by ID.  Returns true if found and removed.
    bool cancel(uint64_t order_id);

    // Find an order by ID without modifying the book.
    std::optional<Order> findOrder(uint64_t order_id) const;

    // Peek at the best bid/ask without removing
    std::optional<Order> peekBid() const;
    std::optional<Order> peekAsk() const;

    // Fast best-order view for matching (no copy)
    const Order* bestBidPtr() const;
    const Order* bestAskPtr() const;

    // Remove the front order from the best bid/ask level
    void popBid();
    void popAsk();

    // Reduce the front order's quantity on the best bid/ask
    void reduceFrontBid(double qty);
    void reduceFrontAsk(double qty);

    // Get a snapshot of the top `depth` price levels on each side
    OrderBookSnapshot getSnapshot(int depth = 20) const;

    // Helpers
    bool hasBids() const;
    bool hasAsks() const;
    double bestBidPrice() const;
    double bestAskPrice() const;

    // Number of resting orders (all levels)
    size_t bidOrderCount() const;
    size_t askOrderCount() const;

private:
    struct PriceLevel {
        std::deque<Order> orders;
        double total_qty = 0.0;
    };

    // bids: highest price first (greater<>)
    std::map<double, PriceLevel, std::greater<double>> bids_;
    // asks: lowest price first (default less<>)
    std::map<double, PriceLevel>                              asks_;
    // fast look-up for cancel
    std::unordered_map<uint64_t, OrderLocation>               index_;

    size_t bid_count_ = 0;
    size_t ask_count_ = 0;
};

} // namespace sb
