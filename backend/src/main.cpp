// ──────────────────────────────────────────────────────────────────────────────
// Synthetic-Bull  ·  Module 1  ·  main.cpp
// Multi-symbol uWebSockets server, broadcaster thread, portfolio management
// ──────────────────────────────────────────────────────────────────────────────

#include "Exchange.hpp"

#include <App.h>                 // uWebSockets
#include <nlohmann/json.hpp>

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

// ─── Per-connection data ─────────────────────────────────────────────────────

struct PerSocketData {
    std::string user_id;
};

// ─── Default symbol configuration ────────────────────────────────────────────

static std::vector<sb::SymbolConfig> getDefaultSymbols() {
    return {
        {"AAPL",   185.00, 0.015, 0.0005, 0.1, 0.0008, 5},
        {"GOOGL",  175.00, 0.014, 0.0004, 0.1, 0.0008, 5},
        {"MSFT",   420.00, 0.013, 0.0006, 0.1, 0.0008, 5},
        {"AMZN",   185.00, 0.016, 0.0003, 0.1, 0.0008, 5},
        {"TSLA",   250.00, 0.035, 0.0010, 0.1, 0.0008, 5},
        {"META",   500.00, 0.018, 0.0005, 0.1, 0.0008, 5},
        {"NVDA",   880.00, 0.030, 0.0020, 0.1, 0.0008, 5},
        {"JPM",    195.00, 0.010, 0.0003, 0.1, 0.0008, 5},
        {"BTC",  50000.00, 0.025, 0.0000, 0.1, 0.0008, 5},
        {"ETH",   3500.00, 0.028, 0.0000, 0.1, 0.0008, 5},
    };
}

// ─── Global state ────────────────────────────────────────────────────────────

static sb::Exchange g_exchange;

// Portfolio per user_id (cash is shared, positions are per-symbol)
static std::unordered_map<std::string, sb::Portfolio> g_portfolios;
static std::mutex g_portfolio_mutex;

// Trade queue (filled by trade callback, drained by broadcaster)
// Each trade already has its symbol tagged
static std::deque<sb::Trade> g_trade_queue;
static std::mutex g_trade_mutex;

// User counter for assigning IDs
static std::atomic<int> g_user_counter{0};

// uWS loop pointer (set once in main)
static uWS::Loop* g_loop = nullptr;

// Global app pointer for deferred publishes
static uWS::App* g_app = nullptr;

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

// ─── Trade callback (called by each MatchingEngine on every fill) ────────────

static void onTrade(const std::string& symbol, const sb::Trade& trade) {
    // 1. Update portfolios
    {
        std::lock_guard<std::mutex> lock(g_portfolio_mutex);

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

    // 2. Feed candle aggregator for this symbol
    auto* state = g_exchange.get(symbol);
    if (state && state->candles) {
        state->candles->addTrade(trade.price, trade.quantity);
    }

    // 3. Push to trade queue for broadcasting
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
            }
        });
    }
}

// ─── main ────────────────────────────────────────────────────────────────────

int main() {
    std::cout << "╔══════════════════════════════════════════════╗\n"
              << "║  Synthetic-Bull  ·  Module 1  ·  v2.0        ║\n"
              << "║  Multi-Symbol Matching Engine + GBM Simulator ║\n"
              << "╚══════════════════════════════════════════════╝\n\n";

    // ── Configure symbols ──
    auto symbol_configs = getDefaultSymbols();

    std::cout << "[~] Configuring " << symbol_configs.size() << " symbols:\n";
    for (auto& cfg : symbol_configs) {
        std::cout << "    " << cfg.symbol
                  << "  $" << cfg.initial_price
                  << "  σ=" << cfg.sigma
                  << "  μ=" << cfg.mu << "\n";
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
        .open = [&symbol_configs](auto* ws) {
            std::string uid = "user_" + std::to_string(++g_user_counter);
            auto* data = ws->getUserData();
            data->user_id = uid;

            // Subscribe to market topic
            ws->subscribe("market");

            // Create portfolio
            {
                std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                g_portfolios[uid] = sb::Portfolio{};
            }

            // 1. Welcome message with all symbols
            json symbols_json = json::array();
            for (auto& cfg : symbol_configs) {
                auto* state = g_exchange.get(cfg.symbol);
                double price = state ? state->simulator->currentPrice() : cfg.initial_price;
                symbols_json.push_back({
                    {"symbol", cfg.symbol},
                    {"price",  std::round(price * 100.0) / 100.0}
                });
            }

            json welcome = {
                {"type", "welcome"},
                {"user_id", uid},
                {"symbols", symbols_json}
            };
            ws->send(welcome.dump(), uWS::OpCode::TEXT);

            // 2. Per-symbol: current order book snapshot + historical candles
            g_exchange.forEachSymbol([&](const std::string& sym, sb::SymbolState& state) {
                // Order book snapshot
                auto snap = state.engine->getSnapshot(20);
                ws->send(obSnapshotToJson(sym, snap).dump(), uWS::OpCode::TEXT);

                // Replay historical candles
                auto candles = state.candles->getHistory(200);
                for (auto& c : candles) {
                    ws->send(candleToJson(sym, c).dump(), uWS::OpCode::TEXT);
                }
            });

            // 3. Portfolio
            {
                std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                auto& pf = g_portfolios[uid];
                ws->send(portfolioToJson(pf).dump(), uWS::OpCode::TEXT);
            }

            std::cout << "[+] " << uid << " connected\n";
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

            // ── ping ──
            if (msg_type == "ping") {
                ws->send(json({{"type", "pong"}, {"ts", sb::now_ms()}}).dump(),
                         uWS::OpCode::TEXT);
                return;
            }

            // ── place_order ──
            if (msg_type == "place_order") {
                std::string symbol   = req.value("symbol", "");
                std::string ot_str   = req.value("order_type", "");
                std::string side_str = req.value("side", "");
                double price = req.value("price", 0.0);
                double qty   = req.value("qty", 0.0);

                // Validate symbol
                auto* state = g_exchange.get(symbol);
                if (!state) {
                    ws->send(json({{"type", "error"},
                                   {"message", "Unknown symbol: " + symbol}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                if (qty <= 0.0) {
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
                                            ? price * qty
                                            : state->simulator->currentPrice() * qty * 1.01;
                    std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                    auto it = g_portfolios.find(uid);
                    if (it != g_portfolios.end() && it->second.cash < order_cost) {
                        ws->send(json({{"type", "error"},
                                       {"message", "Insufficient cash"}}).dump(),
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
                order.quantity = qty;
                order.is_bot   = false;

                int fills = state->engine->processOrder(order);

                // Send ack
                json ack = {
                    {"type", "ack"},
                    {"symbol", symbol},
                    {"order_id", order.id},
                    {"status", "accepted"},
                    {"fills", fills}
                };
                ws->send(ack.dump(), uWS::OpCode::TEXT);

                // Send updated portfolio
                {
                    std::lock_guard<std::mutex> lock(g_portfolio_mutex);
                    auto it = g_portfolios.find(uid);
                    if (it != g_portfolios.end()) {
                        ws->send(portfolioToJson(it->second).dump(),
                                 uWS::OpCode::TEXT);
                    }
                }

                return;
            }

            // ── cancel_order ──
            if (msg_type == "cancel_order") {
                std::string symbol = req.value("symbol", "");
                uint64_t oid = req.value("order_id", (uint64_t)0);

                auto* state = g_exchange.get(symbol);
                if (!state) {
                    ws->send(json({{"type", "error"},
                                   {"message", "Unknown symbol: " + symbol}}).dump(),
                             uWS::OpCode::TEXT);
                    return;
                }

                bool ok = state->engine->cancelOrder(oid);
                json resp = {
                    {"type", "cancel_ack"},
                    {"symbol", symbol},
                    {"order_id", oid},
                    {"success", ok}
                };
                ws->send(resp.dump(), uWS::OpCode::TEXT);
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

    // Start all GBM simulators
    std::cout << "[~] Starting GBM simulators for all symbols...\n";
    g_exchange.startAll();

    // Start the broadcaster (Thread N+1)
    std::cout << "[~] Starting broadcaster (100ms interval)\n";
    std::thread broadcaster(broadcasterThread);
    broadcaster.detach();

    std::cout << "[✓] All systems operational — " << symbol_configs.size()
              << " symbols active — ready for connections\n\n";

    // Run the uWS event loop (blocks forever)
    app.run();

    // Cleanup (never reached in normal operation)
    g_exchange.stopAll();
    return 0;
}
