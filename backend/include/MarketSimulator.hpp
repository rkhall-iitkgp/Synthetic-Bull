#pragma once

#include "MatchingEngine.hpp"
#include <thread>
#include <atomic>
#include <random>
#include <deque>

namespace sb {

class MarketSimulator {
public:
    explicit MarketSimulator(MatchingEngine& engine);
    ~MarketSimulator();

    // ── Tunable parameters (set before start()) ──
    void setSigma(double v)        { sigma_ = v; }
    void setMu(double v)           { mu_ = v; }
    void setDt(double v)           { dt_ = v; }
    void setSpreadPct(double v)    { spread_pct_ = v; }
    void setLevels(int v)          { levels_ = v; }
    void setTickMs(int v)          { tick_ms_ = v; }
    void setMaxBotOrders(int v)    { max_bot_orders_ = v; }
    void setInitialPrice(double v) { price_.store(v); }
    void setSymbol(const std::string& s) { symbol_ = s; }

    // ── Lifecycle ──
    void start();
    void stop();
    bool running() const { return running_.load(); }

    // Current GBM mid price (thread-safe read)
    double currentPrice() const { return price_.load(); }

private:
    void run();            // thread entry point
    void stepPrice();      // one GBM step
    void injectOrders();   // place limit bids & asks
    void pruneOrders();    // cancel excess bot orders

    MatchingEngine& engine_;

    // GBM parameters
    double sigma_       = 0.02;
    double mu_          = 0.0;
    double dt_          = 0.1;
    double spread_pct_  = 0.0008;
    int    levels_      = 5;
    int    tick_ms_     = 20;
    int    max_bot_orders_ = 300;

    std::atomic<double>   price_{50000.0};
    std::atomic<bool>     running_{false};
    std::thread           thread_;
    std::string           symbol_;  // symbol tag for injected orders

    // RNG
    std::mt19937                     rng_{std::random_device{}()};
    std::normal_distribution<double> normal_{0.0, 1.0};

    // Track bot order IDs for pruning
    std::deque<uint64_t> bot_order_ids_;
};

} // namespace sb
