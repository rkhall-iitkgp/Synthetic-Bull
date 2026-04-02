#include "OrderBook.hpp"
#include <algorithm>

namespace sb {

// ─── Add ─────────────────────────────────────────────────────────────────────

void OrderBook::add(const Order& order) {
    if (order.side == Side::BUY) {
        auto& level = bids_[order.price];
        level.orders.push_back(order);
        level.total_qty += order.quantity;
        ++bid_count_;
    } else {
        auto& level = asks_[order.price];
        level.orders.push_back(order);
        level.total_qty += order.quantity;
        ++ask_count_;
    }

    index_[order.id] = {order.side, order.price};
}

// ─── Cancel ──────────────────────────────────────────────────────────────────

bool OrderBook::cancel(uint64_t order_id) {
    auto it = index_.find(order_id);
    if (it == index_.end()) return false;

    const auto [side, price] = it->second;

    if (side == Side::BUY) {
        auto map_it = bids_.find(price);
        if (map_it == bids_.end()) return false;
        auto& level = map_it->second;
        auto& dq = level.orders;
        for (auto dq_it = dq.begin(); dq_it != dq.end(); ++dq_it) {
            if (dq_it->id == order_id) {
                level.total_qty -= dq_it->quantity;
                dq.erase(dq_it);
                --bid_count_;
                if (dq.empty() || level.total_qty <= 1e-12) bids_.erase(map_it);
                index_.erase(it);
                return true;
            }
        }
    } else {
        auto map_it = asks_.find(price);
        if (map_it == asks_.end()) return false;
        auto& level = map_it->second;
        auto& dq = level.orders;
        for (auto dq_it = dq.begin(); dq_it != dq.end(); ++dq_it) {
            if (dq_it->id == order_id) {
                level.total_qty -= dq_it->quantity;
                dq.erase(dq_it);
                --ask_count_;
                if (dq.empty() || level.total_qty <= 1e-12) asks_.erase(map_it);
                index_.erase(it);
                return true;
            }
        }
    }
    return false;
}

std::optional<Order> OrderBook::findOrder(uint64_t order_id) const {
    auto it = index_.find(order_id);
    if (it == index_.end()) return std::nullopt;

    const auto [side, price] = it->second;

    if (side == Side::BUY) {
        auto map_it = bids_.find(price);
        if (map_it == bids_.end()) return std::nullopt;
        const auto& dq = map_it->second.orders;
        for (const auto& o : dq) {
            if (o.id == order_id) return o;
        }
    } else {
        auto map_it = asks_.find(price);
        if (map_it == asks_.end()) return std::nullopt;
        const auto& dq = map_it->second.orders;
        for (const auto& o : dq) {
            if (o.id == order_id) return o;
        }
    }

    return std::nullopt;
}

// ─── Peek ────────────────────────────────────────────────────────────────────

std::optional<Order> OrderBook::peekBid() const {
    const Order* best = bestBidPtr();
    if (!best) return std::nullopt;
    return *best;
}

std::optional<Order> OrderBook::peekAsk() const {
    const Order* best = bestAskPtr();
    if (!best) return std::nullopt;
    return *best;
}

const Order* OrderBook::bestBidPtr() const {
    if (bids_.empty()) return nullptr;
    const auto& level = bids_.begin()->second;
    if (level.orders.empty()) return nullptr;
    return &level.orders.front();
}

const Order* OrderBook::bestAskPtr() const {
    if (asks_.empty()) return nullptr;
    const auto& level = asks_.begin()->second;
    if (level.orders.empty()) return nullptr;
    return &level.orders.front();
}

// ─── Pop ─────────────────────────────────────────────────────────────────────

void OrderBook::popBid() {
    if (bids_.empty()) return;
    auto it = bids_.begin();
    auto& level = it->second;
    auto& dq = level.orders;
    level.total_qty -= dq.front().quantity;
    index_.erase(dq.front().id);
    dq.pop_front();
    --bid_count_;
    if (dq.empty() || level.total_qty <= 1e-12) bids_.erase(it);
}

void OrderBook::popAsk() {
    if (asks_.empty()) return;
    auto it = asks_.begin();
    auto& level = it->second;
    auto& dq = level.orders;
    level.total_qty -= dq.front().quantity;
    index_.erase(dq.front().id);
    dq.pop_front();
    --ask_count_;
    if (dq.empty() || level.total_qty <= 1e-12) asks_.erase(it);
}

// ─── Reduce front ────────────────────────────────────────────────────────────

void OrderBook::reduceFrontBid(double qty) {
    if (bids_.empty()) return;
    auto& level = bids_.begin()->second;
    auto& front = level.orders.front();
    const double consumed = std::min(qty, front.quantity);
    front.quantity -= consumed;
    level.total_qty -= consumed;
    if (front.quantity <= 1e-12) {
        index_.erase(front.id);
        level.orders.pop_front();
        --bid_count_;
        if (level.orders.empty() || level.total_qty <= 1e-12) {
            bids_.erase(bids_.begin());
        }
    }
}

void OrderBook::reduceFrontAsk(double qty) {
    if (asks_.empty()) return;
    auto& level = asks_.begin()->second;
    auto& front = level.orders.front();
    const double consumed = std::min(qty, front.quantity);
    front.quantity -= consumed;
    level.total_qty -= consumed;
    if (front.quantity <= 1e-12) {
        index_.erase(front.id);
        level.orders.pop_front();
        --ask_count_;
        if (level.orders.empty() || level.total_qty <= 1e-12) {
            asks_.erase(asks_.begin());
        }
    }
}

// ─── Snapshot ────────────────────────────────────────────────────────────────

OrderBookSnapshot OrderBook::getSnapshot(int depth) const {
    OrderBookSnapshot snap;
    snap.timestamp = now_us();
    snap.bids.reserve(std::max(depth, 0));
    snap.asks.reserve(std::max(depth, 0));

    int count = 0;
    for (const auto& [price, level] : bids_) {
        if (count >= depth) break;
        snap.bids.push_back({price, level.total_qty, static_cast<int>(level.orders.size())});
        ++count;
    }

    count = 0;
    for (const auto& [price, level] : asks_) {
        if (count >= depth) break;
        snap.asks.push_back({price, level.total_qty, static_cast<int>(level.orders.size())});
        ++count;
    }

    if (!bids_.empty() && !asks_.empty()) {
        double best_bid = bids_.begin()->first;
        double best_ask = asks_.begin()->first;
        snap.mid    = (best_bid + best_ask) / 2.0;
        snap.spread = best_ask - best_bid;
    } else if (!bids_.empty()) {
        snap.mid = bids_.begin()->first;
    } else if (!asks_.empty()) {
        snap.mid = asks_.begin()->first;
    }

    return snap;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

bool   OrderBook::hasBids()       const { return !bids_.empty(); }
bool   OrderBook::hasAsks()       const { return !asks_.empty(); }
double OrderBook::bestBidPrice()  const { return bids_.empty() ? 0.0 : bids_.begin()->first; }
double OrderBook::bestAskPrice()  const { return asks_.empty() ? 0.0 : asks_.begin()->first; }
size_t OrderBook::bidOrderCount() const { return bid_count_; }
size_t OrderBook::askOrderCount() const { return ask_count_; }

} // namespace sb
