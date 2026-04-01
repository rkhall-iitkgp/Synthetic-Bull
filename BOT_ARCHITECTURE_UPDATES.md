# Bot Architecture Updates - Individual Bot Strategy & KPI System

## Overview

The Synthetic Bull bot system has been restructured to support **individual bot instances** with **per-bot strategies and KPIs**. Each bot now has its own strategy configuration, performance metrics, and independent portfolio tracking.

## Previous Architecture

### Issues with the Old System
- **Global Strategy States**: KPI tracking was duplicated across bot types (alpha, market_maker)
- **Hard-coded Bots**: Only "alpha_bot" and "market_maker_bot" existed
- **No Strategy Configuration**: Strategy parameters were fixed in shared config
- **No KPI Persistence**: Performance metrics were in-memory only, not stored in database
- **Shared Metrics**: All bots of the same type shared the same KPI tracker instance
- **Scalability Issues**: Could not create multiple independent bots without code changes

## New Architecture

### Core Components

#### 1. **BotStrategy Model** (`bot_strategies` table)
Stores strategy templates and configurations for bots.

```sql
bot_strategies:
  - id (UUID, PRIMARY KEY)
  - name (String): Strategy display name
  - strategy_type (String): "alpha", "market_maker", "custom"
  - config (JSON): Strategy-specific parameters
  - created_at (DateTime)
  - updated_at (DateTime)
```

**Strategy Configuration Example:**
```json
{
  "strategy_type": "alpha",
  "config": {
    "symbol": "BTC/USD",
    "hurst_window": 100,
    "hurst_trending": 0.55,
    "hurst_mr": 0.45,
    "stop_pct": 0.02,
    "tp_pct": 0.05,
    "max_position_pct": 0.20
  }
}
```

#### 2. **Bot Model** (Updated `bots` table)
Each bot now links to a strategy and has independent tracking.

```sql
bots:
  - id (UUID, PRIMARY KEY)
  - name (String): Bot instance name
  - api_key (String): Unique API key for authentication
  - strategy_id (UUID, FOREIGN KEY): Links to BotStrategy
  - status (String): "active", "paused", "stopped"
  - created_at (DateTime)
  - updated_at (DateTime)
```

#### 3. **BotKPI Model** (New `bot_kpis` table)
Persistent KPI storage for each bot instance.

```sql
bot_kpis:
  - id (UUID, PRIMARY KEY)
  - bot_id (UUID, FOREIGN KEY): Links to Bot
  - strategy_id (UUID, FOREIGN KEY): Links to BotStrategy
  
  # Common KPIs (all strategies)
  - total_trades (Integer)
  - winning_trades (Integer)
  - losing_trades (Integer)
  - total_pnl (Float)
  - realized_pnl (Float)
  - unrealized_pnl (Float)
  - win_rate (Float)
  - max_drawdown (Float)
  - sharpe_ratio (Float)
  
  # Strategy-specific metrics
  - strategy_metrics (JSON): Custom metrics per strategy
  
  - created_at (DateTime)
  - updated_at (DateTime)
```

#### 4. **Portfolio Model** (Existing `portfolios` table)
Tracks capital and positions for each bot independently.

```sql
portfolios:
  - id (UUID, PRIMARY KEY)
  - bot_id (UUID, FOREIGN KEY)
  - cash_balance (Float)
  - initial_capital (Float)
  - updated_at (DateTime)
```

### Relationships

```
BotStrategy (1) ──────┬──── (N) Bot
                      └──── (N) BotKPI

Bot (1) ──────┬──── (N) Portfolio
              ├──── (N) Position
              ├──── (N) Trade
              └──── (N) BotKPI
```

## API Endpoints

### Strategy Management

#### **POST /api/strategies**
Create a new bot strategy template.

**Request:**
```json
{
  "name": "Alpha Strategy v1",
  "strategy_type": "alpha",
  "config": {
    "symbol": "BTC/USD",
    "hurst_window": 100,
    "hurst_trending": 0.55,
    "hurst_mr": 0.45
  }
}
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Alpha Strategy v1",
  "strategy_type": "alpha",
  "config": {...},
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

#### **GET /api/strategies**
List all available strategies.

**Query Parameters:**
- `skip` (int, default: 0)
- `limit` (int, default: 100)

**Response:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Alpha Strategy v1",
    "strategy_type": "alpha",
    "config": {...},
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z"
  }
]
```

#### **GET /api/strategies/{strategy_id}**
Get a specific strategy.

**Response:** Single strategy object

### Bot Management

#### **POST /api/bots** (Updated)
Create a new bot with optional strategy assignment.

**Request:**
```json
{
  "name": "My Alpha Bot 001",
  "strategy_type": "alpha",
  "strategy_config": {
    "symbol": "BTC/USD",
    "hurst_window": 100,
    "hurst_trending": 0.55,
    "hurst_mr": 0.45
  }
}
```

**Response:**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "name": "My Alpha Bot 001",
  "api_key": "sk_live_abc123def456...",
  "strategy_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "active",
  "created_at": "2024-01-15T11:00:00Z",
  "updated_at": "2024-01-15T11:00:00Z"
}
```

#### **GET /api/bots/{bot_id}** (New)
Get detailed bot information including strategy.

**Response:**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "name": "My Alpha Bot 001",
  "api_key": "sk_live_abc123def456...",
  "status": "active",
  "strategy": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Alpha Strategy v1",
    "strategy_type": "alpha",
    "config": {...},
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z"
  },
  "created_at": "2024-01-15T11:00:00Z",
  "updated_at": "2024-01-15T11:00:00Z"
}
```

#### **GET /api/bots**
List all bots (existing endpoint, unchanged).

### KPI Management (New)

#### **GET /api/bots/{bot_id}/kpi**
Get KPI data for a specific bot.

**Response:**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "bot_id": "660e8400-e29b-41d4-a716-446655440001",
  "total_trades": 45,
  "winning_trades": 28,
  "losing_trades": 17,
  "total_pnl": 2500.50,
  "realized_pnl": 2400.00,
  "unrealized_pnl": 100.50,
  "win_rate": 0.6222,
  "max_drawdown": 0.0850,
  "sharpe_ratio": 1.4523,
  "strategy_metrics": {
    "avg_trade_duration_minutes": 45,
    "profit_factor": 2.15,
    "consecutive_losses": 3
  },
  "updated_at": "2024-01-15T15:45:30Z"
}
```

#### **POST /api/bots/{bot_id}/kpi/update**
Update KPI data for a bot (typically called by running bot instances).

**Request:**
```json
{
  "total_trades": 46,
  "winning_trades": 29,
  "losing_trades": 17,
  "total_pnl": 2650.75,
  "realized_pnl": 2550.00,
  "unrealized_pnl": 100.75,
  "win_rate": 0.6304,
  "max_drawdown": 0.0850,
  "sharpe_ratio": 1.5123,
  "strategy_metrics": {
    "avg_trade_duration_minutes": 45,
    "profit_factor": 2.20,
    "consecutive_losses": 0
  }
}
```

**Response:**
```json
{
  "status": "updated",
  "kpi_id": "770e8400-e29b-41d4-a716-446655440002"
}
```

### Existing Endpoints (Unchanged)

- **GET /api/bots/{bot_id}/trades** - Get trades for a bot
- **GET /api/bots/{bot_id}/portfolio** - Get portfolio for a bot
- **GET /api/bots/{bot_id}/pnl** - Get P&L history for a bot
- **POST /api/bots/{bot_id}/deposit** - Deposit funds to a bot

## Usage Examples

### Example 1: Create Strategy and Bot

```bash
# Step 1: Create a strategy template
curl -X POST http://localhost:8000/api/strategies \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Aggressive Alpha",
    "strategy_type": "alpha",
    "config": {
      "symbol": "BTC/USD",
      "hurst_window": 100,
      "max_position_pct": 0.25
    }
  }'

# Response includes strategy_id: "550e8400..."

# Step 2: Create bot using the strategy
curl -X POST http://localhost:8000/api/bots \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Bot Instance 1",
    "strategy_type": "alpha",
    "strategy_config": {
      "symbol": "BTC/USD",
      "hurst_window": 100,
      "max_position_pct": 0.25
    }
  }'

# Response includes bot_id and api_key
```

### Example 2: Retrieve Bot Data

```bash
# Get bot details with strategy
curl http://localhost:8000/api/bots/660e8400-e29b-41d4-a716-446655440001

# Get bot KPIs
curl http://localhost:8000/api/bots/660e8400-e29b-41d4-a716-446655440001/kpi

# Get bot P&L history
curl http://localhost:8000/api/bots/660e8400-e29b-41d4-a716-446655440001/pnl?period=7d
```

### Example 3: Update Bot KPIs (Called by Bot Process)

```bash
# Bot process periodically updates its KPIs
curl -X POST http://localhost:8000/api/bots/660e8400-e29b-41d4-a716-446655440001/kpi/update \
  -H "Content-Type: application/json" \
  -d '{
    "total_trades": 50,
    "winning_trades": 31,
    "losing_trades": 19,
    "total_pnl": 3100.00,
    "win_rate": 0.62,
    "max_drawdown": 0.085,
    "sharpe_ratio": 1.52
  }'
```

## Database Changes

### Migration Steps

1. **Create new tables:**
   - `bot_strategies` table
   - `bot_kpis` table

2. **Alter existing table:**
   - Add `strategy_id` (Foreign Key) to `bots` table
   - Add `updated_at` to `bots` table (for audit trail)

### SQL Migration Script

```sql
-- Create bot_strategies table
CREATE TABLE IF NOT EXISTS bot_strategies (
    id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    strategy_type VARCHAR NOT NULL,
    config JSON DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_strategy_type (strategy_type)
);

-- Create bot_kpis table
CREATE TABLE IF NOT EXISTS bot_kpis (
    id VARCHAR NOT NULL,
    bot_id VARCHAR NOT NULL,
    strategy_id VARCHAR,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_pnl FLOAT DEFAULT 0.0,
    realized_pnl FLOAT DEFAULT 0.0,
    unrealized_pnl FLOAT DEFAULT 0.0,
    win_rate FLOAT DEFAULT 0.0,
    max_drawdown FLOAT DEFAULT 0.0,
    sharpe_ratio FLOAT DEFAULT 0.0,
    strategy_metrics JSON DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (bot_id) REFERENCES bots(id),
    FOREIGN KEY (strategy_id) REFERENCES bot_strategies(id),
    INDEX idx_bot_id (bot_id),
    INDEX idx_strategy_id (strategy_id)
);

-- Alter bots table to add strategy relationship
ALTER TABLE bots 
ADD COLUMN strategy_id VARCHAR,
ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
ADD FOREIGN KEY (strategy_id) REFERENCES bot_strategies(id),
ADD INDEX idx_strategy_id (strategy_id);
```

## Changes Summary

### Modified Files

1. **backend/admin_api/models.py**
   - Added `BotStrategy` model
   - Updated `Bot` model with `strategy_id` and `updated_at` fields
   - Added `BotKPI` model with comprehensive KPI tracking
   - Added relationships between models

2. **backend/admin_api/schemas.py**
   - Added `BotStrategyCreate` and `BotStrategyResponse` schemas
   - Updated `BotCreate` schema to support strategy configuration
   - Added `BotResponse` with `strategy_id` field
   - Added `BotWithStrategyResponse` for detailed bot info
   - Added `BotKPIResponse` schema for KPI data

3. **backend/admin_api/main.py**
   - Added `POST /api/strategies` - Create strategy
   - Added `GET /api/strategies` - List strategies
   - Added `GET /api/strategies/{strategy_id}` - Get specific strategy
   - Updated `POST /api/bots` - Create bot with strategy support
   - Updated `POST /api/bots` - Auto-initialize KPI tracking
   - Added `GET /api/bots/{bot_id}` - Get detailed bot with strategy
   - Added `GET /api/bots/{bot_id}/kpi` - Get bot KPIs
   - Added `POST /api/bots/{bot_id}/kpi/update` - Update KPIs

## Benefits of New Architecture

### 1. **Scalability**
- ✅ Create unlimited independent bot instances
- ✅ Each bot has its own strategy and portfolio
- ✅ No interference between different bots

### 2. **Flexibility**
- ✅ Reuse strategies across multiple bots
- ✅ Store strategy configs in database (no code changes needed)
- ✅ Support custom strategies beyond alpha/market_maker

### 3. **Observability**
- ✅ Persistent KPI data for historical analysis
- ✅ Compare performance across bots
- ✅ Track KPI changes over time
- ✅ Strategy-specific custom metrics

### 4. **Maintainability**
- ✅ Clear separation of concerns
- ✅ Strategy templates decouple from instances
- ✅ Easier to add new strategy types
- ✅ Audit trail with created_at/updated_at timestamps

### 5. **Performance Tracking**
- ✅ Individual win rates, Sharpe ratios, max drawdown per bot
- ✅ Real-time KPI updates
- ✅ Historical KPI snapshots in database
- ✅ Customizable metrics per strategy type

## Migration Guide

### For Existing Systems

If upgrading from the old architecture:

1. **Backup your database**
2. **Run migration scripts** to create new tables and alter existing ones
3. **Update bot initialization code** to work with new models
4. **Provide strategy_type** when creating new bots
5. **Update KPI tracking code** to write to `bot_kpis` table

### For New Deployments

Simply use the updated API as described in the endpoints section above. The system will automatically:
- Create strategy records when you create bots
- Initialize KPI tracking
- Set up portfolio and position tracking

## Next Steps

1. **Implement KPI Writers**: Update bot processes to write KPIs to database
2. **Dashboard Integration**: Connect frontend to new KPI endpoints
3. **Strategy Optimization**: Add endpoints for backtesting strategies
4. **Analytics**: Build reports comparing multiple bots
5. **Alerts**: Set up alerts when KPIs cross thresholds

## Technical Specifications

### Entity Relationships

```
┌─────────────────┐
│ BotStrategy     │
├─────────────────┤
│ id (PK)         │
│ name            │
│ strategy_type   │
│ config (JSON)   │
└────────┬────────┘
         │
         │ (1:N)
         │
    ┌────▼─────────────┐
    │ Bot              │─────────────────┐
    ├──────────────────┤                 │
    │ id (PK)          │                 │
    │ name             │                 │
    │ api_key          │                 │
    │ strategy_id (FK) │                 │
    │ status           │                 │
    │ created_at       │                 │
    │ updated_at       │                 │
    └────┬─────────────┘                 │
         │                               │
         │ (1:N)                         │ (1:N)
         │                               │
    ┌────▼──────────┐             ┌──────▼──────┐
    │ Portfolio     │             │ BotKPI      │
    │ Position      │             ├─────────────┤
    │ Trade         │             │ id (PK)     │
    └───────────────┘             │ bot_id (FK) │
                                  │ strategy_id │
                                  │ KPI metrics │
                                  └─────────────┘
```

## Questions & Support

For integration questions:
1. Check the API documentation in this file
2. Review the example usage scenarios
3. Ensure all models and schemas are properly imported
4. Verify database migrations have been applied
