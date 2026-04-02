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

// ─── Heston + Jump Diffusion price step ──────────────────────────────────────
//
// Heston SDE:
//   dS = (mu - jump_compensation)*S*dt + sqrt(v)*S*dW1
//   dv = kappa*(theta - v)*dt + xi*sqrt(v)*dW2
//   corr(dW1, dW2) = rho
//
// Merton jump:
//   with probability lambda*dt, multiply S by exp(jump_mean + jump_std*N(0,1))
//   jump_compensation = lambda * (exp(jump_mean + 0.5*jump_std^2) - 1.0)
//
// Circuit breaker: clamp single-tick move to ±max_tick_move_pct_

void MarketSimulator::stepPrice() {
    double S = price_.load();
    double v = variance_;

    // ── Correlated Brownian motions ──
    double Z1_idio = normal_(rng_);
    double Z_market = market_factor_.load();  // shared factor set externally

    // Mix market factor with idiosyncratic noise
    double Z1 = beta_ * Z_market + std::sqrt(1.0 - beta_ * beta_) * Z1_idio;

    // Z2 correlated with Z1 via rho
    double Z2 = rho_ * Z1 + std::sqrt(1.0 - rho_ * rho_) * normal_(rng_);

    // ── Heston variance step ──
    double sqrt_v  = std::sqrt(std::max(v, 1e-6));
    double sqrt_dt = std::sqrt(dt_);

    double v_new = v + kappa_ * (theta_ - v) * dt_
                     + xi_ * sqrt_v * sqrt_dt * Z2;
    // Reflection scheme: use abs to prevent negative variance, floor at 1e-6
    v_new = std::max(std::abs(v_new), 1e-6);
    variance_ = v_new;

    // ── Jump compensation (prevents long-term drift from jumps) ──
    double jump_comp = 0.0;
    if (jump_intensity_ > 0.0) {
        jump_comp = jump_intensity_ * (std::exp(jump_mean_ + 0.5 * jump_std_ * jump_std_) - 1.0);
    }

    // ── Heston price step (GBM with stochastic vol) ──
    double drift     = (mu_ - jump_comp - 0.5 * v) * dt_;
    double diffusion = sqrt_v * sqrt_dt * Z1;

    double log_return = drift + diffusion;

    // ── Merton jump (Poisson sampling) ──
    if (jump_intensity_ > 0.0 && uniform_(rng_) < jump_intensity_ * dt_) {
        double J = jump_mean_ + jump_std_ * normal_(rng_);
        log_return += J;  // additive in log-space = multiplicative in price
    }

    // ── Circuit breaker: cap single-tick move ──
    log_return = std::clamp(log_return, -max_tick_move_pct_, max_tick_move_pct_);

    S *= std::exp(log_return);
    S  = std::clamp(S, 0.01, 10000000.0);
    price_.store(S);
}

// ─── Inventory-aware, asymmetric order injection ─────────────────────────────
//
// The sim_bot skews its quotes based on its net inventory:
//   - If long (positive inventory): widen bids, tighten asks → encourage selling
//   - If short (negative inventory): widen asks, tighten bids → encourage buying
//
// Volume clustering: activity_ scales order quantity (evolves in log-space)
// Dynamic spread: spread widens when current vol > long-run vol

void MarketSimulator::injectOrders() {
    double mid = price_.load();
    double inv = inventory_.load();

    // ── Volume clustering (log-space evolution) ──
    log_activity_ += 0.1 * (0.0 - log_activity_) * dt_  // mean-revert to 0 (= activity 1.0)
                   + 0.2 * normal_(rng_) * std::sqrt(dt_);
    double activity = std::clamp(std::exp(log_activity_), 0.2, 5.0);

    // ── Dynamic spread: widen when vol is high ──
    double sigma_long_run = std::sqrt(theta_);  // long-run sigma
    double vol_ratio = (sigma_long_run > 1e-8)
                     ? std::sqrt(variance_) / sigma_long_run
                     : 1.0;
    double dynamic_spread = spread_pct_ * std::clamp(vol_ratio, 0.5, 4.0);

    // ── Inventory skew ──
    double skew = skew_factor_ * inv;

    for (int lvl = 1; lvl <= levels_; ++lvl) {
        double base_offset = dynamic_spread * lvl;

        // Skew offsets: positive inventory → push bids down, pull asks closer
        double bid_offset = base_offset + skew;
        double ask_offset = base_offset - skew;

        // Ensure offsets stay positive (can't bid above mid)
        bid_offset = std::max(bid_offset, dynamic_spread * 0.2);
        ask_offset = std::max(ask_offset, dynamic_spread * 0.2);

        // Randomise quantity, scaled by activity
        double base_qty = 0.01 + 0.04 * uniform_(rng_);
        double bid_qty = base_qty * activity;
        double ask_qty = base_qty * activity;

        // Inventory limit logic (can be toggled off)
        bool place_bid = true;
        bool place_ask = true;
        if (use_inventory_limit_) {
            // Reduce quantity on the side we're overexposed on
            if (inv > inventory_limit_ * 0.5)  bid_qty *= 0.3;
            if (inv < -inventory_limit_ * 0.5) ask_qty *= 0.3;

            // Stop quoting entirely if at inventory limit
            place_bid = (inv < inventory_limit_);
            place_ask = (inv > -inventory_limit_);
        }

        // Limit BID
        if (place_bid) {
            Order bid;
            bid.user_id  = "sim_mm_bot";
            bid.symbol   = symbol_;
            bid.side     = Side::BUY;
            bid.type     = OrderType::LIMIT;
            bid.price    = mid * (1.0 - bid_offset);
            bid.quantity = bid_qty;
            bid.is_bot   = true;
            int fills = engine_.processOrder(bid);
            bot_order_ids_.push_back(bid.id);

            // Update inventory if filled (atomic, outside engine mutex)
            if (fills > 0) {
                inventory_.store(inventory_.load() + bid_qty);
            }
        }

        // Limit ASK
        if (place_ask) {
            Order ask;
            ask.user_id  = "sim_mm_bot";
            ask.symbol   = symbol_;
            ask.side     = Side::SELL;
            ask.type     = OrderType::LIMIT;
            ask.price    = mid * (1.0 + ask_offset);
            ask.quantity = ask_qty;
            ask.is_bot   = true;
            int fills = engine_.processOrder(ask);
            bot_order_ids_.push_back(ask.id);

            // Update inventory if filled (atomic, outside engine mutex)
            if (fills > 0) {
                inventory_.store(inventory_.load() - ask_qty);
            }
        }
    }
}

// ─── Prune old bot orders ────────────────────────────────────────────────────

void MarketSimulator::pruneOrders() {
    while (static_cast<int>(bot_order_ids_.size()) > max_bot_orders_) {
        uint64_t oldest = bot_order_ids_.front();
        bot_order_ids_.pop_front();
        engine_.cancelOrder(oldest);   // may already be filled — that's fine
    }
}

} // namespace sb
