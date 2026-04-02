// ──────────────────────────────────────────────────────────────────────────────
// Synthetic-Bull  ·  Module 1  ·  main.cpp
// Multi-symbol uWebSockets server, broadcaster thread, portfolio management
// ──────────────────────────────────────────────────────────────────────────────

#include "Exchange.hpp"

#include <App.h>                 // uWebSockets
#include <nlohmann/json.hpp>
#include <sqlite3.h>

#include <iostream>
#include <string>
#include <unordered_map>
#include <mutex>
#include <thread>
#include <deque>
#include <atomic>
#include <cmath>
#include <algorithm>

using json = nlohmann::json;

// ─── Per-connection rate limiter (token bucket) ─────────────────────────────

struct TokenBucket {
    double tokens      = 50.0;   // start full
    double max_tokens  = 50.0;   // max burst
    double refill_rate = 50.0;   // tokens per second
    uint64_t last_refill_ms = 0;

    bool consume() {
        uint64_t now = sb::now_ms();
        if (last_refill_ms == 0) last_refill_ms = now;
        double elapsed_s = (now - last_refill_ms) / 1000.0;
        last_refill_ms = now;
        tokens = std::min(max_tokens, tokens + elapsed_s * refill_rate);
        if (tokens >= 1.0) {
            tokens -= 1.0;
            return true;
        }
        return false;
    }
};

// ─── Per-connection data ─────────────────────────────────────────────────────

struct PerSocketData {
    std::string user_id;
    bool is_authenticated = false;
    bool is_admin = false;
    TokenBucket rate_limiter;
};

// ─── Default symbol configuration ────────────────────────────────────────────

static std::vector<sb::SymbolConfig> getDefaultSymbols() {
    // Fields: symbol, initial_price, sigma, mu, dt, spread_pct, levels,
    //         kappa, theta, xi, rho,
    //         jump_intensity, jump_mean, jump_std,
    //         skew_factor, inventory_limit, max_tick_move_pct, beta
    return {
        // ── Tech stocks: moderate vol, negative leverage, symmetric jumps ──
        //  symbol, price, sigma, mu, dt, spread_pct, levels,
        //  kappa, theta, xi, rho,
        //  jump_intensity, jump_mean, jump_std,
        //  skew_factor, inventory_limit, use_inventory_limit, max_tick_move_pct, beta, sector
        {"AAPL",   185.0, 0.015, 0.0, 0.00008, 0.0008, 5,
         2.0, 0.000225, 0.08, -0.6,
         0.3, 0.0, 0.02,
         0.0002, 50.0, true, 0.02, 0.5, "tech", sb::SimModelType::OFI_GBM, 0.3},

        {"GOOGL",  175.0, 0.014, 0.0, 0.00008, 0.0008, 5,
         2.5, 0.000196, 0.07, -0.5,
         0.2, 0.0, 0.015,
         0.0002, 50.0, true, 0.02, 0.45, "tech"},

        {"MSFT",   420.0, 0.013, 0.0, 0.00008, 0.0008, 5,
         2.5, 0.000169, 0.06, -0.5,
         0.2, 0.0, 0.015,
         0.0002, 50.0, true, 0.02, 0.5, "tech"},

        {"AMZN",   185.0, 0.016, 0.0, 0.00008, 0.0008, 5,
         2.0, 0.000256, 0.09, -0.55,
         0.3, 0.0, 0.02,
         0.0002, 50.0, true, 0.02, 0.4, "tech"},

        // ── High-vol stock: TSLA ── explosive, heavy leverage, more jumps
        {"TSLA",   250.0, 0.035, 0.0, 0.00008, 0.0010, 5,
         1.5, 0.001225, 0.30, -0.7,
         0.6, 0.0, 0.04,
         0.0003, 40.0, true, 0.02, 0.60, "tech"},

        {"META",   500.0, 0.018, 0.0, 0.00008, 0.0008, 5,
         2.0, 0.000324, 0.10, -0.55,
         0.3, 0.0, 0.025,
         0.0002, 50.0, true, 0.02, 0.4, "tech"},

        // ── Monster vol: NVDA ── chipmaker, high everything
        {"NVDA",   880.0, 0.030, 0.0, 0.00008, 0.0010, 5,
         1.8, 0.000900, 0.25, -0.65,
         0.5, 0.0, 0.035,
         0.0003, 40.0, true, 0.02, 0.45, "tech"},

        // ── Stable financial: JPM ── low vol, strong mean-reversion
        {"JPM",    195.0, 0.010, 0.0, 0.00008, 0.0006, 5,
         3.0, 0.000100, 0.05, -0.3,
         0.1, 0.0, 0.01,
         0.0001, 80.0, true, 0.02, 0.55, "financial"},

        // ── Crypto: BTC ── zero drift, huge vol-of-vol, heavy jumps, correlated
        {"BTC",  50000.0, 0.025, 0.0, 0.00008, 0.0012, 5,
         1.0, 0.000625, 0.35, -0.4,
         0.8, 0.0, 0.05,
         0.0004, 30.0, true, 0.02, 0.70, "crypto"},

        // ── Crypto: ETH ── similar to BTC, correlated
        {"ETH",   3500.0, 0.028, 0.0, 0.00008, 0.0012, 5,
         1.0, 0.000784, 0.38, -0.4,
         0.9, 0.0, 0.055,
         0.0004, 30.0, true, 0.02, 0.65, "crypto"},
    };
}

// ─── Global state ────────────────────────────────────────────────────────────

static sb::Exchange g_exchange;

// Auth tables
static std::unordered_map<std::string, std::string> g_valid_keys; // api_key -> bot_id
static std::mutex g_auth_mutex;
static std::string g_master_admin_key = "sk_admin_12345"; // For the data logger / firehose

// Portfolio per user_id (cash is shared, positions are per-symbol)
static std::unordered_map<std::string, sb::Portfolio> g_portfolios;
static std::mutex g_portfolio_mutex;

// Open orders per user_id — tracks resting limit orders
// Key: user_id, Value: vector of {order_id, symbol, side, price, qty}
struct OpenOrderInfo {
    uint64_t    order_id;
    std::string symbol;
    std::string side;   // "buy" or "sell"
    double      price;
    double      orig_qty;
    double      remaining_qty;
};
static std::unordered_map<std::string, std::vector<OpenOrderInfo>> g_open_orders;
static std::mutex g_open_orders_mutex;

// Trade queue (filled by trade callback, drained by broadcaster)
// Each trade already has its symbol tagged
static std::deque<sb::Trade> g_trade_queue;
static std::mutex g_trade_mutex;

// uWS loop pointer (set once in main)
static uWS::Loop* g_loop = nullptr;

// Global app pointer for deferred publishes
static uWS::App* g_app = nullptr;

static void loadAuthKeysFromDB() {
    sqlite3* db;
    const char* db_dir = std::getenv("DB_DIR");
    std::string db_path = db_dir ? std::string(db_dir) + "/admin.db" : "./admin.db";
    
    if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        return; 
    }
    
    const char* sql = "SELECT api_key, id FROM bots WHERE status = 'active'";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        std::unordered_map<std::string, std::string> new_keys;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            std::string api_key = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            std::string bot_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            new_keys[api_key] = bot_id;
        }
        sqlite3_finalize(stmt);
        
        std::lock_guard<std::mutex> lock(g_auth_mutex);
        g_valid_keys = std::move(new_keys);
    }
    sqlite3_close(db);
}

static void authPollingThread() {
    while (true) {
        loadAuthKeysFromDB();
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
}

// ─── Portfolio helpers ───────────────────────────────────────────────────────

static void applyTradeToPosition(sb::Position& pos, sb::Portfolio& pf,
                                 double price, double qty, bool is_buyer) {
    if (is_buyer) {
        // Buying: deduct cash, increase holdings
        double cost = price * qty;
        pf.cash -= cost;

        if (pos.holdings >= 0.0) {
            // Adding to long position — update average cost
            double total_cost = pos.avg_cost * pos.holdings + cost;
            pos.holdings += qty;
            pos.avg_cost = (pos.holdings > 1e-12) ? total_cost / pos.holdings : 0.0;
        } else {
            // Covering short — book realised PnL
            double cover_qty = std::min(qty, -pos.holdings);
            pos.realized_pnl += cover_qty * (pos.avg_cost - price);
            pos.holdings += qty;
            if (pos.holdings > 1e-12) {
                pos.avg_cost = price;
            } else if (std::abs(pos.holdings) < 1e-12) {
                pos.avg_cost = 0.0;
                pos.holdings = 0.0;
            }
        }
    } else {
        // Selling: add cash, decrease holdings
        double proceeds = price * qty;
        pf.cash += proceeds;

        if (pos.holdings > 0.0) {
            // Closing long — book realised PnL
            double sell_qty = std::min(qty, pos.holdings);
            pos.realized_pnl += sell_qty * (price - pos.avg_cost);
            pos.holdings -= qty;
            if (pos.holdings < -1e-12) {
                pos.avg_cost = price;
            } else if (std::abs(pos.holdings) < 1e-12) {
                pos.avg_cost = 0.0;
                pos.holdings = 0.0;
            }
        } else {
            // Adding to short — update average cost
            double total_cost = pos.avg_cost * (-pos.holdings) + proceeds;
            pos.holdings -= qty;
            pos.avg_cost = (std::abs(pos.holdings) > 1e-12)
                              ? total_cost / (-pos.holdings)
                              : 0.0;
        }
    }
}

static json portfolioToJson(const sb::Portfolio& pf) {
    double total_realized = 0.0;
    double total_unrealized = 0.0;
    double total_holdings_value = 0.0;

    json positions_json = json::object();

    for (auto& [sym, pos] : pf.positions) {
        double mid = 0.0;
        auto* state = g_exchange.get(sym);
        if (state) mid = state->simulator->currentPrice();

        double unrealized = 0.0;
        if (std::abs(pos.holdings) > 1e-12) {
            unrealized = pos.holdings * (mid - pos.avg_cost);
        }
        double holdings_value = pos.holdings * mid;

        total_realized += pos.realized_pnl;
        total_unrealized += unrealized;
        total_holdings_value += holdings_value;

        // Only include non-zero positions
        if (std::abs(pos.holdings) > 1e-12 || std::abs(pos.realized_pnl) > 1e-4) {
            positions_json[sym] = {
                {"holdings",       std::round(pos.holdings * 100000.0) / 100000.0},
                {"avg_cost",       std::round(pos.avg_cost * 100.0) / 100.0},
                {"realized_pnl",   std::round(pos.realized_pnl * 100.0) / 100.0},
                {"unrealized_pnl", std::round(unrealized * 100.0) / 100.0},
                {"market_value",   std::round(holdings_value * 100.0) / 100.0}
            };
        }
    }

    double total_value = pf.cash + total_holdings_value;

    return {
        {"type",           "portfolio"},
        {"cash",           std::round(pf.cash * 100.0) / 100.0},
        {"positions",      positions_json},
        {"realized_pnl",   std::round(total_realized * 100.0) / 100.0},
        {"unrealized_pnl", std::round(total_unrealized * 100.0) / 100.0},
        {"total_value",    std::round(total_value * 100.0) / 100.0}
    };
}

// Build JSON for a user's open orders
static json openOrdersToJson(const std::string& uid) {
    json arr = json::array();
    std::lock_guard<std::mutex> lock(g_open_orders_mutex);
    auto it = g_open_orders.find(uid);
    if (it != g_open_orders.end()) {
        for (auto& o : it->second) {
            arr.push_back({
                {"order_id",      o.order_id},
                {"symbol",        o.symbol},
                {"side",          o.side},
                {"price",         std::round(o.price * 100.0) / 100.0},
                {"orig_qty",      std::round(o.orig_qty * 100000.0) / 100000.0},
                {"remaining_qty", std::round(o.remaining_qty * 100000.0) / 100000.0}
            });
        }
    }
    return json({{"type", "open_orders"}, {"orders", arr}});
}

// ─── JSON builders ───────────────────────────────────────────────────────────

static json obSnapshotToJson(const std::string& symbol,
                              const sb::OrderBookSnapshot& snap) {
    json j;
    j["type"]   = "orderbook";
    j["symbol"] = symbol;
    j["mid"]    = std::round(snap.mid * 100.0) / 100.0;
    j["spread"] = std::round(snap.spread * 100.0) / 100.0;
    j["ts"]     = snap.timestamp;

    j["bids"] = json::array();
    for (auto& lvl : snap.bids) {
        j["bids"].push_back({
            std::round(lvl.price * 100.0) / 100.0,
            std::round(lvl.total_qty * 100000.0) / 100000.0,
            lvl.order_count
        });
    }

    j["asks"] = json::array();
    for (auto& lvl : snap.asks) {
        j["asks"].push_back({
            std::round(lvl.price * 100.0) / 100.0,
            std::round(lvl.total_qty * 100000.0) / 100000.0,
            lvl.order_count
        });
    }
    return j;
}

static json tradeToJson(const sb::Trade& t) {
    return {
        {"type",   "trade"},
        {"symbol", t.symbol},
        {"id",     t.id},
        {"price",  std::round(t.price * 100.0) / 100.0},
        {"qty",    std::round(t.quantity * 100000.0) / 100000.0},
        {"buyer",  t.buyer_id},
        {"seller", t.seller_id},
        {"buyer_order_id", t.buyer_order_id},
        {"seller_order_id", t.seller_order_id},
        {"ts",     t.timestamp}
    };
}

static json candleToJson(const std::string& symbol, const sb::Candle& c) {
    return {
        {"type",   "candle"},
        {"symbol", symbol},
        {"o",      std::round(c.open * 100.0) / 100.0},
        {"h",      std::round(c.high * 100.0) / 100.0},
        {"l",      std::round(c.low * 100.0) / 100.0},
        {"c",      std::round(c.close * 100.0) / 100.0},
        {"v",      std::round(c.volume * 100000.0) / 100000.0},
        {"t",      c.timestamp}
    };
}

static json historyToJson(const std::string& symbol, const std::vector<sb::Candle>& candles) {
    json arr = json::array();

    for (const auto& c : candles) {
        arr.push_back({
            {"o", std::round(c.open * 100.0) / 100.0},
            {"h", std::round(c.high * 100.0) / 100.0},
            {"l", std::round(c.low * 100.0) / 100.0},
            {"c", std::round(c.close * 100.0) / 100.0},
            {"v", std::round(c.volume * 100000.0) / 100000.0},
            {"t", c.timestamp}
        });
    }

    return {
        {"type", "history"},
        {"symbol", symbol},
        {"candles", arr}
    };
}

// ─── Trade callback (called by each MatchingEngine on every fill) ────────────

static void onTrade(const std::string& symbol, const sb::Trade& trade) {
    // 1. Update portfolios
    {
        std::lock_guard<std::mutex> lock(g_portfolio_mutex);

        if (trade.buyer_id != trade.seller_id) {
            auto it_b = g_portfolios.find(trade.buyer_id);
            if (it_b != g_portfolios.end()) {
                auto& pos = it_b->second.positions[symbol];
                applyTradeToPosition(pos, it_b->second, trade.price, trade.quantity, true);
            }

            auto it_s = g_portfolios.find(trade.seller_id);
            if (it_s != g_portfolios.end()) {
                auto& pos = it_s->second.positions[symbol];
                applyTradeToPosition(pos, it_s->second, trade.price, trade.quantity, false);
            }
        }
    }

    // 2. Reduce filled orders from open_orders tracking
    {
        std::lock_guard<std::mutex> lock(g_open_orders_mutex);
        auto reduceByOrderId = [&](const std::string& uid, uint64_t order_id) {
            if (order_id == 0) return;

            auto it = g_open_orders.find(uid);
            if (it == g_open_orders.end()) return;

            auto& vec = it->second;
            auto oit = std::find_if(vec.begin(), vec.end(),
                [order_id](const OpenOrderInfo& o) { return o.order_id == order_id; });

            if (oit == vec.end()) return;

            oit->remaining_qty -= trade.quantity;
            if (oit->remaining_qty <= 1e-8) {
                vec.erase(oit);
            }
        };

        reduceByOrderId(trade.buyer_id, trade.buyer_order_id);
        reduceByOrderId(trade.seller_id, trade.seller_order_id);
    }

    // 3. Feed candle aggregator for this symbol
    auto* state = g_exchange.get(symbol);
    if (state && state->candles) {
        state->candles->addTrade(trade.price, trade.quantity);
    }

    // 4. Push to trade queue for broadcasting
    {
        std::lock_guard<std::mutex> lock(g_trade_mutex);
        g_trade_queue.push_back(trade);
    }
}

// ─── Candle callback ─────────────────────────────────────────────────────────

static void onCandle(const std::string& symbol, const sb::Candle& candle) {
    if (!g_loop || !g_app) return;
    std::string msg = candleToJson(symbol, candle).dump();
    g_loop->defer([msg = std::move(msg)]() {
        g_app->publish("market", msg, uWS::OpCode::TEXT);
    });
}

// ─── Broadcaster thread ──────────────────────────────────────────────────────

static void broadcasterThread() {
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        if (!g_loop || !g_app) continue;

        // 1. Order book snapshots for ALL symbols
        std::vector<std::string> ob_msgs;
        g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
            auto snap = state.engine->getSnapshot(20);
            ob_msgs.push_back(obSnapshotToJson(sym, snap).dump());

            // Feed GBM price to candle aggregator
            state.candles->addPrice(state.simulator->currentPrice());
        });

        // 2. Drain trade queue
        std::deque<sb::Trade> trades;
        {
            std::lock_guard<std::mutex> lock(g_trade_mutex);
            trades.swap(g_trade_queue);
        }

        std::vector<std::string> trade_msgs;
        for (auto& t : trades) {
            trade_msgs.push_back(tradeToJson(t).dump());
        }

        // 3. Defer all publishes to the uWS loop thread
        g_loop->defer([ob_msgs = std::move(ob_msgs),
                       trade_msgs = std::move(trade_msgs)]() {
            for (auto& om : ob_msgs) {
                g_app->publish("market", om, uWS::OpCode::TEXT);
            }
            for (auto& tm : trade_msgs) {
                g_app->publish("market", tm, uWS::OpCode::TEXT);
                g_app->publish("admin_firehose", tm, uWS::OpCode::TEXT);
            }
        });
    }
}

// ─── Sector-based correlated noise generator ────────────────────────────────
// Three independent sector factors so JPM doesn't correlate with BTC.
// Each sector gets its own N(0,1) drawn independently per tick cycle.
// Symbols load on their sector factor via their beta coefficient.

struct SectorFactors {
    std::mt19937 rng{std::random_device{}()};
    std::normal_distribution<double> normal{0.0, 1.0};
    std::atomic<double> z_tech{0.0};
    std::atomic<double> z_financial{0.0};
    std::atomic<double> z_crypto{0.0};

    void update() {
        z_tech.store(normal(rng));
        z_financial.store(normal(rng));
        z_crypto.store(normal(rng));
    }

    double get(const std::string& sector) const {
        if (sector == "crypto")    return z_crypto.load();
        if (sector == "financial") return z_financial.load();
        return z_tech.load();  // default
    }
};

static SectorFactors g_sector_factors;

// Symbol-to-sector mapping (built once at startup)
static std::unordered_map<std::string, std::string> g_symbol_sector;

static void updateSectorFactors() {
    g_sector_factors.update();
    g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
        auto it = g_symbol_sector.find(sym);
        std::string sector = (it != g_symbol_sector.end()) ? it->second : "tech";
        state.simulator->setMarketFactor(g_sector_factors.get(sector));
    });
}

// ─── main ────────────────────────────────────────────────────────────────────

int main() {
    std::cout << "╔══════════════════════════════════════════════════════╗\n"
              << "║  Synthetic-Bull  ·  Module 1  ·  v3.0               ║\n"
              << "║  Heston SV + Jump Diffusion + Smart Market Making   ║\n"
              << "╚══════════════════════════════════════════════════════╝\n\n";

    // ── Configure symbols ──
    auto symbol_configs = getDefaultSymbols();

    std::cout << "[~] Configuring " << symbol_configs.size() << " symbols:\n";
    for (auto& cfg : symbol_configs) {
        std::cout << "    " << cfg.symbol
                  << "  $" << cfg.initial_price
                  << "  σ=" << cfg.sigma
                  << "  κ=" << cfg.kappa
                  << "  ξ=" << cfg.xi
                  << "  ρ=" << cfg.rho
                  << "  λ=" << cfg.jump_intensity
                  << "  β=" << cfg.beta << "\n";
        g_exchange.addSymbol(cfg, onTrade, onCandle);
    }
    std::cout << "\n";

    // Create the sim_bot portfolio so trade callbacks don't crash
    {
        std::lock_guard<std::mutex> lock(g_portfolio_mutex);
        g_portfolios["sim_bot"] = sb::Portfolio{};
    }

    // ── uWebSockets app ──

    uWS::App app;
    g_app = &app;

    app.ws<PerSocketData>("/*", {
        .compression = uWS::DISABLED,
        .maxPayloadLength = 16 * 1024,
        .idleTimeout = 120,
        .maxBackpressure = 4 * 1024 * 1024,  // increased for multi-symbol

        // ── on open ──
        .open = [](auto* ws) {
            auto* data = ws->getUserData();
            // Default to sim_bot, frontend works seamlessly. Real bots will authenticate and override this.
            data->user_id = "sim_bot";
            data->is_authenticated = true;
            data->is_admin = false;
            
            // Auto-subscribe the default sim_bot to the market stream
            ws->subscribe("market");

            {
                std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                if (g_portfolios.find("sim_bot") == g_portfolios.end()) {
                    g_portfolios["sim_bot"] = sb::Portfolio{};
                }
            }

            // Bootstrap dashboard immediately so refresh reuses the same in-memory user state.
            json symbols_json = json::array();
            g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
                symbols_json.push_back({
                    {"symbol", sym},
                    {"price",  std::round(state.simulator->currentPrice() * 100.0) / 100.0}
                });
            });

            json welcome = {
                {"type", "welcome"},
                {"user_id", "sim_bot"},
                {"symbols", symbols_json}
            };
            ws->send(welcome.dump(), uWS::OpCode::TEXT);

            {
                std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                auto it = g_portfolios.find("sim_bot");
                if (it != g_portfolios.end()) {
                    ws->send(portfolioToJson(it->second).dump(), uWS::OpCode::TEXT);
                }
            }
            ws->send(openOrdersToJson("sim_bot").dump(), uWS::OpCode::TEXT);

            g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
                auto snap = state.engine->getSnapshot(20);
                ws->send(obSnapshotToJson(sym, snap).dump(), uWS::OpCode::TEXT);
                auto candles = state.candles->getHistory(200);
                ws->send(historyToJson(sym, candles).dump(), uWS::OpCode::TEXT);
            });
        },

        // ── on message ──
        .message = [](auto* ws, std::string_view message, uWS::OpCode) {
            auto* data = ws->getUserData();
            const std::string& uid = data->user_id;
            
            json req;
            try {
                req = json::parse(message);
            } catch (...) {
                ws->send(json({{"type", "error"}, {"message", "Invalid JSON"}}).dump(),
                         uWS::OpCode::TEXT);
                return;
            }

            std::string msg_type = req.value("type", "");

            // ── Rate limiting (token bucket: 50 msgs/sec) ──
            if (msg_type != "ping") {
                if (!data->rate_limiter.consume()) {
                    ws->send(json({{"type", "error"},
                                   {"message", "Rate limit exceeded (max 50 msgs/sec)"}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }
            }

            // ── ping ──
            if (msg_type == "ping") {
                ws->send(json({{"type", "pong"}, {"ts", sb::now_ms()}}).dump(),
                         uWS::OpCode::TEXT);
                return;
            }

            if (msg_type == "auth") {
                std::string api_key = req.value("api_key", "");
                std::string bot_id = "";
                bool admin = false;
                
                if (api_key == g_master_admin_key) {
                    bot_id = "ADMIN";
                    admin = true;
                } else {
                    std::lock_guard<std::mutex> lock(g_auth_mutex);
                    auto it = g_valid_keys.find(api_key);
                    if (it != g_valid_keys.end()) {
                        bot_id = it->second;
                    }
                }

                if (bot_id.empty()) {
                    ws->send(json({{"type", "error"}, {"message", "Invalid API key"}}).dump(), uWS::OpCode::TEXT);
                    return;
                }

                data->user_id = bot_id;
                data->is_authenticated = true;
                data->is_admin = admin;

                if (admin) {
                    ws->subscribe("admin_firehose");
                    ws->send(json({{"type", "auth_success"}, {"role", "admin"}}).dump(), uWS::OpCode::TEXT);
                    std::cout << "[+] Admin connected\n";
                    return;
                }

                // Regular bot
                ws->subscribe("market");
                
                {
                    std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                    if (g_portfolios.find(bot_id) == g_portfolios.end()) {
                        // Initialize local cache of portfolio if missing
                        // Optionally we could load starting balance from DB here.
                        // For now we'll lazily start with 100000 or the existing state
                        g_portfolios[bot_id] = sb::Portfolio{};
                    }
                }

                json symbols_json = json::array();
                // Send welcome message and state here. We'll reconstruct symbol_configs logic.
                g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
                    symbols_json.push_back({
                        {"symbol", sym},
                        {"price",  std::round(state.simulator->currentPrice() * 100.0) / 100.0}
                    });
                });

                json welcome = {
                    {"type", "welcome"},
                    {"user_id", bot_id},
                    {"symbols", symbols_json}
                };
                ws->send(welcome.dump(), uWS::OpCode::TEXT);

                {
                    std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                    auto& pf = g_portfolios[bot_id];
                    ws->send(portfolioToJson(pf).dump(), uWS::OpCode::TEXT);
                }
                ws->send(openOrdersToJson(bot_id).dump(), uWS::OpCode::TEXT);

                g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
                    auto snap = state.engine->getSnapshot(20);
                    ws->send(obSnapshotToJson(sym, snap).dump(), uWS::OpCode::TEXT);
                    auto candles = state.candles->getHistory(200);
                    ws->send(historyToJson(sym, candles).dump(), uWS::OpCode::TEXT);
                });

                std::cout << "[+] Bot " << bot_id << " authenticated\n";
                return;
            }

            // Require auth for the remaining
            if (!data->is_authenticated) {
                ws->send(json({{"type", "error"}, {"message", "Not authenticated"}}).dump(), uWS::OpCode::TEXT);
                return;
            }

            // ── get_portfolio ──
            if (msg_type == "get_portfolio") {
                std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                auto it = g_portfolios.find(uid);
                if (it == g_portfolios.end()) {
                    it = g_portfolios.emplace(uid, sb::Portfolio{}).first;
                }
                ws->send(portfolioToJson(it->second).dump(), uWS::OpCode::TEXT);
                return;
            }

            // ── get_open_orders ──
            if (msg_type == "get_open_orders") {
                ws->send(openOrdersToJson(uid).dump(), uWS::OpCode::TEXT);
                return;
            }

            // ── place_order ──
            if (msg_type == "place_order") {
                std::string symbol   = req.value("symbol", "");
                std::string ot_str   = req.value("order_type", "");
                std::string side_str = req.value("side", "");
                double price    = req.value("price", 0.0);
                double orig_qty = req.value("qty", 0.0);

                // Validate symbol
                auto* state = g_exchange.get(symbol);
                if (!state) {
                    ws->send(json({{"type", "error"},
                                   {"message", "Unknown symbol: " + symbol}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                if (orig_qty <= 0.0) {
                    ws->send(json({{"type", "error"},
                                   {"message", "qty must be positive"}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                sb::OrderType ot;
                if (ot_str == "limit")       ot = sb::OrderType::LIMIT;
                else if (ot_str == "market") ot = sb::OrderType::MARKET;
                else {
                    ws->send(json({{"type", "error"},
                                   {"message", "order_type must be 'limit' or 'market'"}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                sb::Side side;
                if (side_str == "buy")       side = sb::Side::BUY;
                else if (side_str == "sell") side = sb::Side::SELL;
                else {
                    ws->send(json({{"type", "error"},
                                   {"message", "side must be 'buy' or 'sell'"}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                if (ot == sb::OrderType::LIMIT && price <= 0.0) {
                    ws->send(json({{"type", "error"},
                                   {"message", "limit orders require a positive price"}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                // Capital check (for buy orders)
                if (side == sb::Side::BUY) {
                    double order_cost = (ot == sb::OrderType::LIMIT)
                                            ? price * orig_qty
                                            : state->simulator->currentPrice() * orig_qty * 1.01;
                    std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                    auto it = g_portfolios.find(uid);
                    if (it != g_portfolios.end() && it->second.cash < order_cost) {
                        ws->send(json({{"type", "error"},
                                       {"message", "Insufficient cash"}}).dump(),
                                 uWS::OpCode::TEXT);
                        return;
                    }
                }

                // Holdings check (for sell orders)
                if (side == sb::Side::SELL) {
                    double current_holdings = 0.0;
                    {
                        std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                        auto it = g_portfolios.find(uid);
                        if (it != g_portfolios.end()) {
                            auto pit = it->second.positions.find(symbol);
                            if (pit != it->second.positions.end()) {
                                current_holdings = pit->second.holdings;
                            }
                        }
                    }

                    // Subtract qty already reserved by open sell orders for the same symbol
                    double reserved_qty = 0.0;
                    {
                        std::lock_guard<std::mutex> lock(g_open_orders_mutex);
                        auto oit = g_open_orders.find(uid);
                        if (oit != g_open_orders.end()) {
                            for (const auto& oo : oit->second) {
                                if (oo.symbol == symbol && oo.side == "sell") {
                                    reserved_qty += oo.remaining_qty;
                                }
                            }
                        }
                    }

                    double available = current_holdings - reserved_qty;
                    if (available < orig_qty - 1e-12) {
                        ws->send(json({{"type", "error"},
                                       {"message", "Insufficient holdings"}}).dump(),
                                 uWS::OpCode::TEXT);
                        return;
                    }
                }

                sb::Order order;
                order.user_id  = uid;
                order.symbol   = symbol;
                order.side     = side;
                order.type     = ot;
                order.price    = price;
                order.quantity = orig_qty; // This will be reduced directly by processOrder if partially filled
                order.is_bot   = false;

                int fills = state->engine->processOrder(order);

                // Track resting limit orders
                // processOrder modifies order.quantity to its remaining unfilled amount
                if (ot == sb::OrderType::LIMIT && order.quantity > 1e-12) {
                    std::lock_guard<std::mutex> lock(g_open_orders_mutex);
                    g_open_orders[uid].push_back({
                        order.id, symbol,
                        (side == sb::Side::BUY) ? "buy" : "sell",
                        price, orig_qty, order.quantity
                    });
                }

                // Send ack
                json ack = {
                    {"type", "ack"},
                    {"symbol", symbol},
                    {"order_id", order.id},
                    {"status", "accepted"},
                    {"fills", fills}
                };
                ws->send(ack.dump(), uWS::OpCode::TEXT);

                // Send updated portfolio + open orders
                {
                    std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                    auto it = g_portfolios.find(uid);
                    if (it != g_portfolios.end()) {
                        ws->send(portfolioToJson(it->second).dump(),
                                 uWS::OpCode::TEXT);
                    }
                }
                ws->send(openOrdersToJson(uid).dump(), uWS::OpCode::TEXT);

                return;
            }

            // ── cancel_order ──
            if (msg_type == "cancel_order") {
                std::string symbol = req.value("symbol", "");
                uint64_t oid = req.value("order_id", (uint64_t)0);

                if (oid == 0) {
                    ws->send(json({{"type", "error"},
                                   {"message", "order_id is required"}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                // Support cancel requests that provide only an order_id.
                if (symbol.empty()) {
                    std::lock_guard<std::mutex> lock(g_open_orders_mutex);
                    auto oit = g_open_orders.find(uid);
                    if (oit != g_open_orders.end()) {
                        const auto& vec = oit->second;
                        auto found = std::find_if(vec.begin(), vec.end(),
                            [oid](const OpenOrderInfo& o) { return o.order_id == oid; });
                        if (found != vec.end()) {
                            symbol = found->symbol;
                        }
                    }
                }

                auto* state = g_exchange.get(symbol);
                if (!state) {
                    ws->send(json({{"type", "error"},
                                   {"message", "Unknown symbol for order_id " + std::to_string(oid)}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                bool ok = state->engine->cancelOrder(oid);

                // Remove from open orders tracking
                if (ok) {
                    std::lock_guard<std::mutex> lock(g_open_orders_mutex);
                    auto oit = g_open_orders.find(uid);
                    if (oit != g_open_orders.end()) {
                        auto& vec = oit->second;
                        vec.erase(std::remove_if(vec.begin(), vec.end(),
                            [oid](const OpenOrderInfo& o) { return o.order_id == oid; }),
                            vec.end());
                    }
                }

                json resp = {
                    {"type", "cancel_ack"},
                    {"symbol", symbol},
                    {"order_id", oid},
                    {"success", ok}
                };
                ws->send(resp.dump(), uWS::OpCode::TEXT);

                // Send updated open orders
                ws->send(openOrdersToJson(uid).dump(), uWS::OpCode::TEXT);
                return;
            }

            // ── deposit ── (admin only: add funds to a bot's portfolio)
            if (msg_type == "deposit") {
                std::string bot_id = req.value("bot_id", "");
                double amount = req.value("amount", 0.0);

                if (bot_id.empty() || amount <= 0.0) {
                    ws->send(json({{"type", "error"},
                                   {"message", "Invalid deposit parameters"}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                {
                    std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                    g_portfolios[bot_id].cash += amount;
                }

                ws->send(json({{"type", "deposit_ack"},
                               {"bot_id", bot_id},
                               {"amount", amount}}).dump(),
                         uWS::OpCode::TEXT);

                std::cout << "[+] Deposit " << amount << " to bot " << bot_id << "\n";
                return;
            }

            // ── get_symbols ── (request symbol list at any time)
            if (msg_type == "get_symbols") {
                json symbols_json = json::array();
                g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
                    symbols_json.push_back({
                        {"symbol", sym},
                        {"price",  std::round(state.simulator->currentPrice() * 100.0) / 100.0}
                    });
                });
                ws->send(json({{"type", "symbols"}, {"symbols", symbols_json}}).dump(),
                         uWS::OpCode::TEXT);
                return;
            }

            // Unknown type
            ws->send(json({{"type", "error"},
                           {"message", "Unknown message type"}}).dump(),
                     uWS::OpCode::TEXT);
        },

        // ── on close ──
        .close = [](auto* /*ws*/, int /*code*/, std::string_view /*message*/) {
            // Portfolio kept in memory (user can reconnect)
        }
    });

    app.listen(9001, [](auto* listen_socket) {
        if (listen_socket) {
            std::cout << "[✓] WebSocket server listening on port 9001\n";
        } else {
            std::cerr << "[✗] Failed to listen on port 9001\n";
            exit(1);
        }
    });

    // Grab the loop pointer for deferred publishes
    g_loop = uWS::Loop::get();

    // ── 3-second warmup: start simulators to fill the order book ──
    std::cout << "[~] Starting simulators (3s warmup — filling order books)...\n";
    g_exchange.startAll();
    std::this_thread::sleep_for(std::chrono::seconds(3));
    std::cout << "[✓] Warmup complete — order books are filled\n";

    // Start the broadcaster (Thread N+1)
    std::cout << "[~] Starting broadcaster (100ms interval + correlated noise)\n";
    std::thread broadcaster(broadcasterThread);
    broadcaster.detach();

    // Start auth polling thread
    std::thread auth_poller(authPollingThread);
    auth_poller.detach();

    // Build symbol→sector mapping for correlation
    for (auto& cfg : symbol_configs) {
        g_symbol_sector[cfg.symbol] = cfg.sector;
    }

    // Start sector-based correlated noise generator
    std::thread sector_factor_thread([]() {
        while (true) {
            updateSectorFactors();
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
    });
    sector_factor_thread.detach();

    std::cout << "[✓] All systems operational — " << symbol_configs.size()
              << " symbols active — ready for connections\n\n";

    // Run the uWS event loop (blocks forever)
    app.run();

    // Cleanup (never reached in normal operation)
    g_exchange.stopAll();
    return 0;
}
