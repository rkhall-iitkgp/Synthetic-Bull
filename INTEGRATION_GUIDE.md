# Integration Guide - Per-Bot Strategy & KPI System

## Quick Start

### 1. Database Setup

```bash
# Start your database server
docker-compose up -d db

# Run migrations (handled automatically by SQLAlchemy)
# The models.py will create tables on first run
cd backend/admin_api
python main.py
# Tables will be created on startup
```

### 2. Create Your First Bot With Strategy

```python
import requests

BASE_URL = "http://localhost:8000"

# Step 1: Create a strategy
strategy_response = requests.post(
    f"{BASE_URL}/api/strategies",
    json={
        "name": "Alpha Strategy v1",
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
)
strategy = strategy_response.json()
print(f"Created strategy: {strategy['id']}")

# Step 2: Create bot with strategy
bot_response = requests.post(
    f"{BASE_URL}/api/bots",
    json={
        "name": "Alpha Bot Instance 001",
        "strategy_type": "alpha",
        "strategy_config": {
            "symbol": "BTC/USD",
            "hurst_window": 100,
            "hurst_trending": 0.55,
            "hurst_mr": 0.45,
            "stop_pct": 0.02,
            "tp_pct": 0.05,
            "max_position_pct": 0.20
        }
    }
)
bot = bot_response.json()
print(f"Created bot: {bot['id']}")
print(f"API Key: {bot['api_key']}")
```

### 3. Running a Bot Instance

Each bot process should now update KPIs after trades:

```python
# In your bot's main.py
import requests
from datetime import datetime

class Bot:
    def __init__(self, bot_id: str, api_base: str = "http://localhost:8000"):
        self.bot_id = bot_id
        self.api_base = api_base
        self.trades_count = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        
    def after_trade(self, trade_pnl: float):
        """Called after each trade execution"""
        self.trades_count += 1
        self.total_pnl += trade_pnl
        
        if trade_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Update KPIs periodically (e.g., every 10 trades)
        if self.trades_count % 10 == 0:
            self.update_kpis()
    
    def update_kpis(self):
        """Push current KPIs to backend"""
        win_rate = self.winning_trades / self.trades_count if self.trades_count > 0 else 0
        
        requests.post(
            f"{self.api_base}/api/bots/{self.bot_id}/kpi/update",
            json={
                "total_trades": self.trades_count,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "total_pnl": round(self.total_pnl, 2),
                "win_rate": round(win_rate, 4),
                "strategy_metrics": {
                    "avg_pnl_per_trade": round(self.total_pnl / self.trades_count, 2) if self.trades_count > 0 else 0
                }
            }
        )
        print(f"Updated KPIs for bot {self.bot_id}")
```

## Multi-Bot Management

### Managing Multiple Bot Instances

```python
# Create 5 different bot instances with same strategy template
base_config = {
    "symbol": "BTC/USD",
    "hurst_window": 100,
    "max_position_pct": 0.20
}

bots = []
for i in range(5):
    response = requests.post(
        f"{BASE_URL}/api/bots",
        json={
            "name": f"Alpha Bot #{i+1:03d}",
            "strategy_type": "alpha",
            "strategy_config": base_config
        }
    )
    bots.append(response.json())
    print(f"Created bot {i+1}: {bots[i]['id']}")

# Now each bot is completely independent
# Get KPIs for all bots
for bot in bots:
    kpi_response = requests.get(f"{BASE_URL}/api/bots/{bot['id']}/kpi")
    kpi = kpi_response.json()
    print(f"\n{bot['name']}:")
    print(f"  Trades: {kpi['total_trades']}")
    print(f"  Win Rate: {kpi['win_rate']*100:.2f}%")
    print(f"  PnL: ${kpi['total_pnl']:,.2f}")
```

## Architecture Comparison

### Before (Old)
```
Global State
├── alpha_kpi_tracker (shared by all alpha bots)
├── market_maker_kpi_tracker (shared by all MM bots)
└── Fixed strategy parameters in config.py

Problems:
- Can't run multiple alpha bots independently
- All metrics mixed together
- No persistence
- Config changes affect all instances
```

### After (New)
```
Per-Bot Instance
├── Bot 1 (ID: xyz-001)
│   ├── Strategy: Alpha v1 (independent config)
│   ├── Portfolio: Individual capital allocation
│   ├── KPI Tracker: Individual metrics in database
│   └── Trades: Separate trade history
├── Bot 2 (ID: xyz-002)
│   ├── Strategy: Alpha v1 (same template, independent)
│   ├── Portfolio: Separate capital
│   ├── KPI Tracker: Completely separate metrics
│   └── Trades: Separate history
└── Bot 3 (ID: xyz-003)
    ├── Strategy: Market Maker v1 (different strategy)
    ├── Portfolio: Separate capital
    ├── KPI Tracker: Different metrics tracked
    └── Trades: Separate history

Benefits:
- Unlimited independent bot instances
- Complete metric isolation
- Persistent historical data
- Per-bot configuration
```

## Data Model Visualization

### Database Schema

```
┌──────────────────┐       ┌──────────────────┐
│  BotStrategy     │       │      Bot         │
├──────────────────┤       ├──────────────────┤
│ id (PK)          │◄──────│ strategy_id (FK) │
│ name             │  1-N  │ name             │
│ strategy_type    │       │ api_key          │
│ config (JSON)    │       │ status           │
│ created_at       │       │ created_at       │
│ updated_at       │       │ updated_at       │
└──────────────────┘       └────┬─────────────┘
                                │
                        ┌───────┴────────┐
                        │                │
                   ┌────▼────────┐ ┌────▼──────────┐
                   │ Portfolio   │ │   BotKPI      │
                   ├─────────────┤ ├───────────────┤
                   │ bot_id (FK) │ │ bot_id (FK)   │
                   │ cash_balance│ │ win_rate      │
                   └─────────────┘ │ sharpe_ratio  │
                                  │ max_drawdown  │
                   ┌────────────┐  │ total_pnl     │
                   │ Position   │  │ ...           │
                   ├────────────┤  └───────────────┘
                   │ bot_id(FK) │
                   │ symbol     │
                   │ qty        │
                   └────────────┘

                   ┌────────────┐
                   │ Trade      │
                   ├────────────┤
                   │ bot_id(FK) │
                   │ symbol     │
                   │ side       │
                   │ price      │
                   │ qty        │
                   └────────────┘
```

## API Usage Patterns

### Pattern 1: Create Bot and Start Trading

```bash
# 1. Create bot
BOT=$(curl -s -X POST http://localhost:8000/api/bots \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Trading Bot 001",
    "strategy_type": "alpha",
    "strategy_config": {"symbol": "BTC/USD"}
  }')

BOT_ID=$(echo $BOT | jq -r '.id')
API_KEY=$(echo $BOT | jq -r '.api_key')

# 2. Deposit initial capital
curl -X POST http://localhost:8000/api/bots/$BOT_ID/deposit \
  -H "Content-Type: application/json" \
  -d '{"amount": 50000}'

# 3. Start bot process with BOT_ID and API_KEY
python bots/alpha/main.py --bot-id=$BOT_ID --api-key=$API_KEY

# 4. Monitor KPIs
while true; do
  curl http://localhost:8000/api/bots/$BOT_ID/kpi | jq '.'
  sleep 60
done
```

### Pattern 2: Compare Multiple Bots

```bash
# Get all bots
BOTS=$(curl -s http://localhost:8000/api/bots | jq '.[]')

echo "Bot Performance Summary"
echo "======================="

echo "$BOTS" | jq -r '.id' | while read BOT_ID; do
  BOT=$(curl -s http://localhost:8000/api/bots/$BOT_ID)
  KPI=$(curl -s http://localhost:8000/api/bots/$BOT_ID/kpi)
  
  echo "Bot: $(echo $BOT | jq -r '.name')"
  echo "  Strategy: $(echo $BOT | jq -r '.strategy.strategy_type')"
  echo "  Trades: $(echo $KPI | jq '.total_trades')"
  echo "  Win Rate: $(echo $KPI | jq '.win_rate * 100 | round' 2)%"
  echo "  Sharpe: $(echo $KPI | jq '.sharpe_ratio')"
  echo "  PnL: \$$(echo $KPI | jq '.total_pnl' 2)"
  echo ""
done
```

### Pattern 3: Backtest and Deploy Strategy

```python
def backtest_and_deploy_strategy(strategy_config):
    """
    1. Backtest strategy
    2. If successful, create live bot
    3. Monitor performance
    """
    import requests
    
    # Run backtest (implementation in your backtest system)
    backtest_results = run_backtest(strategy_config)
    
    if backtest_results['sharpe_ratio'] > 1.0:
        # Good results, create live bot
        response = requests.post(
            f"{BASE_URL}/api/bots",
            json={
                "name": f"Bot-{backtest_results['timestamp']}",
                "strategy_type": strategy_config['type'],
                "strategy_config": strategy_config
            }
        )
        bot = response.json()
        return bot['id'], bot['api_key']
    else:
        print("Backtest results insufficient to deploy")
        return None, None
```

## Monitoring and Observability

### Real-time Bot Dashboard Data

```python
def get_bot_dashboard_data(bot_id: str):
    """Fetch complete bot status for dashboard"""
    import requests
    
    # Get bot info
    bot = requests.get(f"{BASE_URL}/api/bots/{bot_id}").json()
    
    # Get portfolio
    portfolio = requests.get(f"{BASE_URL}/api/bots/{bot_id}/portfolio").json()
    
    # Get KPIs
    kpi = requests.get(f"{BASE_URL}/api/bots/{bot_id}/kpi").json()
    
    # Get recent trades
    trades = requests.get(f"{BASE_URL}/api/bots/{bot_id}/trades?limit=10").json()
    
    # Get PnL history
    pnl = requests.get(f"{BASE_URL}/api/bots/{bot_id}/pnl?period=7d").json()
    
    return {
        "bot": bot,
        "portfolio": portfolio,
        "kpi": kpi,
        "recent_trades": trades,
        "pnl_history": pnl
    }

# Usage in dashboard
dashboard_data = get_bot_dashboard_data(bot_id)
print(f"Current Equity: ${dashboard_data['portfolio']['cash_balance']}")
print(f"Win Rate: {dashboard_data['kpi']['win_rate']*100:.2f}%")
print(f"Total PnL: ${dashboard_data['kpi']['total_pnl']}")
```

## Troubleshooting

### Issue: Bot KPIs not persisting
**Solution**: Ensure your bot process is calling `/api/bots/{bot_id}/kpi/update` endpoint

### Issue: Can't create bot with strategy
**Solution**: Verify strategy_type is one of: "alpha", "market_maker", "custom"

### Issue: Multiple bots sharing metrics
**Solution**: Each bot now has isolated KPI records. Check that you're querying the correct bot_id

### Issue: Database migration failing
**Solution**: 
1. Backup your database
2. Ensure SQLAlchemy has write permissions
3. Check database logs for specific errors

## Performance Considerations

### KPI Update Frequency
- **Too frequent** (every trade): May impact performance
- **Recommended**: Update every 10-50 trades or on a time interval (e.g., every minute)

### Database Load
- Each bot can have 1000s of trades
- Use query pagination: `?limit=100&skip=0`
- Archive old trades to separate table if needed

### Scaling Multiple Bots
- Each bot process is independent
- Run on separate machines for isolation
- Use load balancer in front of API
- Consider read replicas for KPI queries

## Next Steps

1. **Update Bot Processes**: Modify your bot code to use the new API key approach
2. **Integration Tests**: Test creating and managing multiple bots
3. **Dashboard Updates**: Connect your dashboard to new KPI endpoints
4. **Alerts**: Set up KPI threshold alerts
5. **Analytics**: Build reports comparing bot performance
