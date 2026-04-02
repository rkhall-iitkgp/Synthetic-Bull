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

    // ── Basic GBM parameters ──
    void setSigma(double v)        { sigma_ = v; variance_ = v * v; }
    void setMu(double v)           { mu_ = v; }
    void setDt(double v)           { dt_ = v; }
    void setSpreadPct(double v)    { spread_pct_ = v; }
    void setLevels(int v)          { levels_ = v; }
    void setTickMs(int v)          { tick_ms_ = v; }
    void setMaxBotOrders(int v)    { max_bot_orders_ = v; }
    void setInitialPrice(double v) { price_.store(v); }
    void setSymbol(const std::string& s) { symbol_ = s; }

    // ── Simulation Model Toggle ──
    void setModelType(SimModelType type) { model_type_ = type; }
    void setGamma(double v)        { gamma_ = v; }

    // ── Heston stochastic volatility ──
    void setKappa(double v)  { kappa_ = v; }
    void setTheta(double v)  { theta_ = v; }
    void setXi(double v)     { xi_ = v; }
    void setRho(double v)    { rho_ = v; }

    // ── Merton jump diffusion ──
    void setJumpIntensity(double v) { jump_intensity_ = v; }
    void setJumpMean(double v)      { jump_mean_ = v; }
    void setJumpStd(double v)       { jump_std_ = v; }

    // ── Inventory-aware market making ──
    void setSkewFactor(double v)     { skew_factor_ = v; }
    void setInventoryLimit(double v) { inventory_limit_ = v; }
    void setUseInventoryLimit(bool v) { use_inventory_limit_ = v; }

    // ── Circuit breaker ──
    void setMaxTickMovePct(double v) { max_tick_move_pct_ = v; }

    // ── Asset correlation ──
    void setBeta(double v) { beta_ = v; }

    // ── Shared market factor (set externally each tick cycle) ──
    void setMarketFactor(double z) { market_factor_.store(z); }

    // ── Lifecycle ──
    void start();
    void stop();
    bool running() const { return running_.load(); }

    // Current mid price (thread-safe read)
    double currentPrice() const { return price_.load(); }

    // Current instantaneous volatility (sqrt of variance_)
    double currentVol() const { return std::sqrt(std::max(variance_, 1e-6)); }

private:
    void run();            // thread entry point
    void stepPrice();      // Heston + jump diffusion step
    void injectOrders();   // inventory-aware market making
    void pruneOrders();    // cancel excess bot orders

    MatchingEngine& engine_;

    // ── GBM base parameters ──
    double sigma_       = 0.02;
    double mu_          = 0.0;
    double dt_          = 0.00008;  // ≈1 trading-second per tick (annualized)
    double spread_pct_  = 0.0008;
    int    levels_      = 5;
    int    tick_ms_     = 20;
    int    max_bot_orders_ = 300;

    // ── Simulation Model Toggle & OFI Variables ──
    SimModelType model_type_ = SimModelType::HESTON_JUMP;
    double gamma_            = 0.2;
    double prev_bid_price_   = 0.0;
    double prev_ask_price_   = 0.0;
    double prev_bid_qty_     = 0.0;
    double prev_ask_qty_     = 0.0;

    // ── Heston stochastic volatility ──
    double variance_    = 0.0004;  // v_t (instantaneous variance, init = sigma²)
    double kappa_       = 2.0;     // mean-reversion speed
    double theta_       = 0.0004;  // long-run variance
    double xi_          = 0.1;     // vol-of-vol
    double rho_         = -0.5;    // price-vol correlation

    // ── Merton jump diffusion ──
    double jump_intensity_ = 0.0;  // λ (0 = disabled)
    double jump_mean_      = -0.02;
    double jump_std_       = 0.03;

    // ── Inventory-aware market making ──
    std::atomic<double> inventory_{0.0};  // net bot position (atomic to avoid deadlock)
    double skew_factor_     = 0.0002;
    double inventory_limit_ = 50.0;
    bool   use_inventory_limit_ = true;

    // ── Volume clustering ──
    double log_activity_ = 0.0;  // evolve in log-space for stability

    // ── Circuit breaker ──
    double max_tick_move_pct_ = 0.02;  // 2% max per tick (tightened for correct dt_)

    // ── Asset correlation ──
    double beta_ = 0.0;
    std::atomic<double> market_factor_{0.0};

    // ── Price & control ──
    std::atomic<double>   price_{50000.0};
    std::atomic<bool>     running_{false};
    std::thread           thread_;
    std::string           symbol_;

    // ── RNG ──
    std::mt19937                          rng_{std::random_device{}()};
    std::normal_distribution<double>      normal_{0.0, 1.0};
    std::uniform_real_distribution<double> uniform_{0.0, 1.0};

    // Track bot order IDs for pruning
    std::deque<uint64_t> bot_order_ids_;
};

} // namespace sb
