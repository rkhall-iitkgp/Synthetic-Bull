#include "MatchingEngine.hpp"
#include <algorithm>

namespace sb {

namespace {
constexpr double kQtyEps = 1e-12;
}

MatchingEngine::MatchingEngine(TradeCallback cb)
    : trade_cb_(std::move(cb)) {}

void MatchingEngine::setTradeCallback(TradeCallback cb) {
    std::lock_guard<std::mutex> lock(mutex_);
    trade_cb_ = std::move(cb);
}

// ─── processOrder ────────────────────────────────────────────────────────────

int MatchingEngine::processOrder(Order& order) {
    // Assign engine-generated ID and timestamp
    order.id        = ++order_counter_;
    order.timestamp = now_us();

    std::vector<Trade> trades;
    trades.reserve(8);
    TradeCallback cb;

    {
        std::lock_guard<std::mutex> lock(mutex_);
        cb = trade_cb_;
        if (order.type == OrderType::LIMIT) {
            matchLimit(order, trades);
        } else {
            matchMarket(order, trades);
        }
    }

    // Fire callbacks OUTSIDE the mutex to prevent deadlock
    for (auto& t : trades) {
        if (cb) cb(t);
    }

    return static_cast<int>(trades.size());
}

// ─── cancelOrder ─────────────────────────────────────────────────────────────

bool MatchingEngine::cancelOrder(uint64_t order_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    return book_.cancel(order_id);
}

bool MatchingEngine::cancelOrderForUser(uint64_t order_id, const std::string& user_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto ord = book_.findOrder(order_id);
    if (!ord.has_value()) return false;
    if (ord->user_id != user_id) return false;
    return book_.cancel(order_id);
}

// ─── getSnapshot ─────────────────────────────────────────────────────────────

OrderBookSnapshot MatchingEngine::getSnapshot(int depth) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return book_.getSnapshot(depth);
}

// ─── matchLimit ──────────────────────────────────────────────────────────────
// Walk the opposite side while the incoming order's price crosses.
// The passive (resting) order's price sets the trade price.

void MatchingEngine::matchLimit(Order& order, std::vector<Trade>& trades) {
    if (order.side == Side::BUY) {
        // Match against asks
        while (order.quantity > kQtyEps) {
            const Order* best = book_.bestAskPtr();
            if (!best || best->price > order.price) break;   // no cross

            double fill_qty   = std::min(order.quantity, best->quantity);
            double fill_price = best->price;   // passive sets price

            Trade t;
            t.id        = ++trade_counter_;
            t.price     = fill_price;
            t.quantity  = fill_qty;
            t.buyer_id  = order.user_id;
            t.seller_id = best->user_id;
            t.buy_order_id  = order.id;
            t.sell_order_id = best->id;
            t.timestamp = now_us();
            trades.push_back(t);

            book_.reduceFrontAsk(fill_qty);
            order.quantity -= fill_qty;
        }
        // Rest unfilled remainder in the book
        if (order.quantity > kQtyEps) {
            book_.add(order);
        }
    } else {
        // SELL — match against bids
        while (order.quantity > kQtyEps) {
            const Order* best = book_.bestBidPtr();
            if (!best || best->price < order.price) break;

            double fill_qty   = std::min(order.quantity, best->quantity);
            double fill_price = best->price;

            Trade t;
            t.id        = ++trade_counter_;
            t.price     = fill_price;
            t.quantity  = fill_qty;
            t.buyer_id  = best->user_id;
            t.seller_id = order.user_id;
            t.buy_order_id  = best->id;
            t.sell_order_id = order.id;
            t.timestamp = now_us();
            trades.push_back(t);

            book_.reduceFrontBid(fill_qty);
            order.quantity -= fill_qty;
        }
        if (order.quantity > kQtyEps) {
            book_.add(order);
        }
    }
}

// ─── matchMarket ─────────────────────────────────────────────────────────────
// Identical to matchLimit but without a price guard.  Never rests in the book.

void MatchingEngine::matchMarket(Order& order, std::vector<Trade>& trades) {
    if (order.side == Side::BUY) {
        while (order.quantity > kQtyEps) {
            const Order* best = book_.bestAskPtr();
            if (!best) break;

            double fill_qty   = std::min(order.quantity, best->quantity);
            double fill_price = best->price;

            Trade t;
            t.id        = ++trade_counter_;
            t.price     = fill_price;
            t.quantity  = fill_qty;
            t.buyer_id  = order.user_id;
            t.seller_id = best->user_id;
            t.buy_order_id  = order.id;
            t.sell_order_id = best->id;
            t.timestamp = now_us();
            trades.push_back(t);

            book_.reduceFrontAsk(fill_qty);
            order.quantity -= fill_qty;
        }
        // Market orders never rest
    } else {
        while (order.quantity > kQtyEps) {
            const Order* best = book_.bestBidPtr();
            if (!best) break;

            double fill_qty   = std::min(order.quantity, best->quantity);
            double fill_price = best->price;

            Trade t;
            t.id        = ++trade_counter_;
            t.price     = fill_price;
            t.quantity  = fill_qty;
            t.buyer_id  = best->user_id;
            t.seller_id = order.user_id;
            t.buy_order_id  = best->id;
            t.sell_order_id = order.id;
            t.timestamp = now_us();
            trades.push_back(t);

            book_.reduceFrontBid(fill_qty);
            order.quantity -= fill_qty;
        }
    }
}

} // namespace sb
