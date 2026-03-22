#include "MarketSimulator.hpp"
#include <cmath>
#include <algorithm>

namespace sb {

MarketSimulator::MarketSimulator(MatchingEngine& engine)
    : engine_(engine) {}

MarketSimulator::~MarketSimulator() {
    stop();
}

// ─── Lifecycle ───────────────────────────────────────────────────────────────

void MarketSimulator::start() {
    if (running_.exchange(true)) return;   // already running
    thread_ = std::thread(&MarketSimulator::run, this);
}

void MarketSimulator::stop() {
    running_.store(false);
    if (thread_.joinable()) thread_.join();
}

// ─── Main loop ───────────────────────────────────────────────────────────────

void MarketSimulator::run() {
    while (running_.load()) {
        stepPrice();
        injectOrders();
        pruneOrders();
        std::this_thread::sleep_for(std::chrono::milliseconds(tick_ms_));
    }
}

// ─── GBM step ────────────────────────────────────────────────────────────────
// S(t+dt) = S(t) * exp( (mu - sigma^2/2)*dt + sigma*sqrt(dt)*Z )

void MarketSimulator::stepPrice() {
    double S  = price_.load();
    double Z  = normal_(rng_);
    double drift     = (mu_ - 0.5 * sigma_ * sigma_) * dt_;
    double diffusion = sigma_ * std::sqrt(dt_) * Z;
    S *= std::exp(drift + diffusion);
    S  = std::clamp(S, 1.0, 1000000.0);
    price_.store(S);
}

// ─── Order injection ─────────────────────────────────────────────────────────
// Place `levels_` limit bids and asks spread around the current mid-price.

void MarketSimulator::injectOrders() {
    double mid = price_.load();

    for (int lvl = 1; lvl <= levels_; ++lvl) {
        double offset = spread_pct_ * lvl;

        // Randomise quantity a bit for realistic depth
        double qty = 0.01 + 0.04 * (static_cast<double>(rng_() % 100) / 100.0);

        // Limit BID
        {
            Order bid;
            bid.user_id  = "sim_bot";
            bid.symbol   = symbol_;
            bid.side     = Side::BUY;
            bid.type     = OrderType::LIMIT;
            bid.price    = mid * (1.0 - offset);
            bid.quantity = qty;
            bid.is_bot   = true;
            engine_.processOrder(bid);
            bot_order_ids_.push_back(bid.id);
        }

        // Limit ASK
        {
            Order ask;
            ask.user_id  = "sim_bot";
            ask.symbol   = symbol_;
            ask.side     = Side::SELL;
            ask.type     = OrderType::LIMIT;
            ask.price    = mid * (1.0 + offset);
            ask.quantity = qty;
            ask.is_bot   = true;
            engine_.processOrder(ask);
            bot_order_ids_.push_back(ask.id);
        }
    }
}

// ─── Prune old bot orders ────────────────────────────────────────────────────
// Cancel oldest bot orders when the resting count exceeds max_bot_orders_.

void MarketSimulator::pruneOrders() {
    while (static_cast<int>(bot_order_ids_.size()) > max_bot_orders_) {
        uint64_t oldest = bot_order_ids_.front();
        bot_order_ids_.pop_front();
        engine_.cancelOrder(oldest);   // may already be filled — that's fine
    }
}

} // namespace sb
