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
enum class SimModelType { HESTON_JUMP, OFI_GBM };

// ─── Symbol configuration ────────────────────────────────────────────────────

struct SymbolConfig {
    std::string symbol;
    double      initial_price = 100.0;
    double      sigma         = 0.02;    // initial volatility (sqrt of initial variance)
    double      mu            = 0.0;     // drift
    double      dt            = 0.00008; // model time step (annualized, ≈1 trading-sec)
    double      spread_pct    = 0.0008;  // base half-spread per level
    int         levels        = 5;       // price levels per tick

    // ── Heston stochastic volatility ──
    double      kappa         = 2.0;     // mean-reversion speed
    double      theta         = 0.0004;  // long-run variance (sigma²)
    double      xi            = 0.1;     // vol-of-vol
    double      rho           = -0.5;    // correlation (price ↔ vol), negative = leverage effect

    // ── Merton jump diffusion ──
    double      jump_intensity = 0.0;    // λ — expected jumps per unit time (0 = disabled)
    double      jump_mean      = 0.0;    // μ_J — average log-jump (0 = symmetric)
    double      jump_std       = 0.03;   // σ_J — jump size std dev

    // ── Inventory-aware market making ──
    double      skew_factor    = 0.0002; // quote skew per unit of inventory
    double      inventory_limit = 50.0;  // max abs inventory before one-side quoting
    bool        use_inventory_limit = true; // toggle inventory limit on/off

    // ── Circuit breaker ──
    double      max_tick_move_pct = 0.02; // max 2% move per tick (tightened for correct dt_)

    // ── Asset correlation ──
    double      beta           = 0.0;    // loading on shared sector factor (0 = uncorrelated)
    std::string sector         = "tech"; // sector group: "tech", "financial", "crypto"

    // ── Simulation Model Toggle ──
    SimModelType model_type = SimModelType::OFI_GBM;

    // ── OFI-Augmented GBM Model ──
    double      gamma         = 0.2;     // OFI price impact strength
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
    uint64_t    buyer_order_id = 0;
    uint64_t    seller_order_id = 0;
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
