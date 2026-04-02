#pragma once

#include "MatchingEngine.hpp"
#include "MarketSimulator.hpp"
#include "CandleAggregator.hpp"

#include <memory>
#include <unordered_map>
#include <vector>
#include <string>
#include <functional>

namespace sb {

// ─── Per-symbol state bundle ─────────────────────────────────────────────────

struct SymbolState {
    SymbolConfig                        config;
    std::unique_ptr<MatchingEngine>     engine;
    std::unique_ptr<MarketSimulator>    simulator;
    std::unique_ptr<CandleAggregator>  candles;
};

// ─── Exchange ────────────────────────────────────────────────────────────────
// Manages multiple symbols, each with its own engine + simulator + candles.

class Exchange {
public:
    using TradeCallback  = std::function<void(const std::string& symbol, const Trade&)>;
    using CandleCallback = std::function<void(const std::string& symbol, const Candle&)>;

    // Add a symbol to the exchange
    void addSymbol(const SymbolConfig& cfg,
                   TradeCallback trade_cb = nullptr,
                   CandleCallback candle_cb = nullptr);

    // Access per-symbol state
    SymbolState*       get(const std::string& symbol);
    const SymbolState* get(const std::string& symbol) const;

    // Get list of all symbols
    std::vector<std::string> symbolList() const;

    // Get list of all symbol configs
    std::vector<SymbolConfig> symbolConfigs() const;

    // Start / stop all simulators
    void startAll();
    void stopAll();

    // Iterate over all symbols
    template<typename Fn>
    void forEachSymbol(Fn&& fn) {
        for (auto& [sym, state] : symbols_) {
            fn(sym, state);
        }
    }

    template<typename Fn>
    void forEachSymbol(Fn&& fn) const {
        for (auto& [sym, state] : symbols_) {
            fn(sym, state);
        }
    }

private:
    std::unordered_map<std::string, SymbolState> symbols_;
};

// ─── Inline implementation ───────────────────────────────────────────────────

inline void Exchange::addSymbol(const SymbolConfig& cfg,
                                TradeCallback trade_cb,
                                CandleCallback candle_cb) {
    auto& state = symbols_[cfg.symbol];
    state.config = cfg;

    // Create engine with a trade callback that tags the symbol
    state.engine = std::make_unique<MatchingEngine>(
        [sym = cfg.symbol, cb = std::move(trade_cb)](const Trade& t) {
            if (cb) {
                Trade tagged = t;
                tagged.symbol = sym;
                cb(sym, tagged);
            }
        }
    );

    // Create simulator
    state.simulator = std::make_unique<MarketSimulator>(*state.engine);
    state.simulator->setSymbol(cfg.symbol);
    state.simulator->setInitialPrice(cfg.initial_price);
    state.simulator->setSigma(cfg.sigma);
    state.simulator->setMu(cfg.mu);
    state.simulator->setDt(cfg.dt);
    state.simulator->setSpreadPct(cfg.spread_pct);
    state.simulator->setLevels(cfg.levels);
    state.simulator->setTickMs(20);
    state.simulator->setMaxBotOrders(300);

    // Simulation Model Toggle & OFI
    state.simulator->setModelType(cfg.model_type);
    state.simulator->setGamma(cfg.gamma);

    // Heston stochastic volatility
    state.simulator->setKappa(cfg.kappa);
    state.simulator->setTheta(cfg.theta);
    state.simulator->setXi(cfg.xi);
    state.simulator->setRho(cfg.rho);

    // Merton jump diffusion
    state.simulator->setJumpIntensity(cfg.jump_intensity);
    state.simulator->setJumpMean(cfg.jump_mean);
    state.simulator->setJumpStd(cfg.jump_std);

    // Inventory-aware market making
    state.simulator->setSkewFactor(cfg.skew_factor);
    state.simulator->setInventoryLimit(cfg.inventory_limit);
    state.simulator->setUseInventoryLimit(cfg.use_inventory_limit);

    // Circuit breaker
    state.simulator->setMaxTickMovePct(cfg.max_tick_move_pct);

    // Asset correlation
    state.simulator->setBeta(cfg.beta);

    // Create candle aggregator with callback
    state.candles = std::make_unique<CandleAggregator>(
        1000,
        [sym = cfg.symbol, cb = candle_cb](const Candle& c) {
            if (cb) {
                Candle tagged = c;
                tagged.symbol = sym;
                cb(sym, tagged);
            }
        }
    );
}

inline SymbolState* Exchange::get(const std::string& symbol) {
    auto it = symbols_.find(symbol);
    return (it != symbols_.end()) ? &it->second : nullptr;
}

inline const SymbolState* Exchange::get(const std::string& symbol) const {
    auto it = symbols_.find(symbol);
    return (it != symbols_.end()) ? &it->second : nullptr;
}

inline std::vector<std::string> Exchange::symbolList() const {
    std::vector<std::string> list;
    list.reserve(symbols_.size());
    for (auto& [sym, _] : symbols_) list.push_back(sym);
    return list;
}

inline std::vector<SymbolConfig> Exchange::symbolConfigs() const {
    std::vector<SymbolConfig> list;
    list.reserve(symbols_.size());
    for (auto& [_, state] : symbols_) list.push_back(state.config);
    return list;
}

inline void Exchange::startAll() {
    for (auto& [sym, state] : symbols_) {
        state.simulator->start();
    }
}

inline void Exchange::stopAll() {
    for (auto& [sym, state] : symbols_) {
        state.simulator->stop();
    }
}

} // namespace sb
