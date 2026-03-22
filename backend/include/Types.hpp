#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <unordered_map>
#include <chrono>
#include <atomic>

namespace sb {

// ─── Enums ───────────────────────────────────────────────────────────────────

enum class Side { BUY, SELL };
enum class OrderType { LIMIT, MARKET };

// ─── Symbol configuration ────────────────────────────────────────────────────

struct SymbolConfig {
    std::string symbol;
    double      initial_price = 100.0;
    double      sigma         = 0.02;    // volatility per GBM step
    double      mu            = 0.0;     // drift (annualised)
    double      dt            = 0.1;     // GBM time step (seconds)
    double      spread_pct    = 0.0008;  // half-spread per level
    int         levels        = 5;       // price levels per tick
};

// ─── Order ───────────────────────────────────────────────────────────────────

struct Order {
    uint64_t    id        = 0;
    std::string user_id;
    std::string symbol;
    Side        side      = Side::BUY;
    OrderType   type      = OrderType::LIMIT;
    double      price     = 0.0;
    double      quantity  = 0.0;
    uint64_t    timestamp = 0;   // microseconds since epoch
    bool        is_bot    = false;
};

// ─── Trade ───────────────────────────────────────────────────────────────────

struct Trade {
    uint64_t    id        = 0;
    std::string symbol;
    double      price     = 0.0;
    double      quantity  = 0.0;
    std::string buyer_id;
    std::string seller_id;
    uint64_t    timestamp = 0;
};

// ─── Candle (OHLCV) ─────────────────────────────────────────────────────────

struct Candle {
    std::string symbol;
    double   open   = 0.0;
    double   high   = 0.0;
    double   low    = 0.0;
    double   close  = 0.0;
    double   volume = 0.0;
    uint64_t timestamp = 0;   // milliseconds since epoch (period start)
};

// ─── Portfolio (multi-symbol) ────────────────────────────────────────────────

struct Position {
    double holdings     = 0.0;
    double avg_cost     = 0.0;
    double realized_pnl = 0.0;
};

struct Portfolio {
    double cash = 100000.0;
    std::unordered_map<std::string, Position> positions;  // per-symbol
};

// ─── Order-book snapshot helpers ─────────────────────────────────────────────

struct OrderBookLevel {
    double price       = 0.0;
    double total_qty   = 0.0;
    int    order_count = 0;
};

struct OrderBookSnapshot {
    std::string symbol;
    double mid    = 0.0;
    double spread = 0.0;
    std::vector<OrderBookLevel> bids;
    std::vector<OrderBookLevel> asks;
    uint64_t timestamp = 0;
};

// ─── Utility ─────────────────────────────────────────────────────────────────

inline uint64_t now_us() {
    using namespace std::chrono;
    return static_cast<uint64_t>(
        duration_cast<microseconds>(
            system_clock::now().time_since_epoch()
        ).count()
    );
}

inline uint64_t now_ms() {
    using namespace std::chrono;
    return static_cast<uint64_t>(
        duration_cast<milliseconds>(
            system_clock::now().time_since_epoch()
        ).count()
    );
}

} // namespace sb
