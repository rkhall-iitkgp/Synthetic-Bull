# KPI Syncing System - Automatic Performance Metrics Tracking

## Overview

Bots now automatically sync their performance metrics (KPIs) to the backend database every 30 seconds (configurable). This means all your bot performance data is persisted and available via the API without any manual intervention.

## How It Works

### Architecture

1. **Local KPI Tracker**: Each bot process (alpha, market_maker) has its own in-memory KPI tracker that collects performance metrics as it trades
2. **KPI Syncer**: A background worker that periodically pushes these metrics to the backend API
3. **Backend Storage**: All KPI data is stored in the `bot_kpis` database table and queryable via API

```
Bot Process (alpha/mm)
├── LocalKPITracker (in-memory)
│   ├── total_trades
│   ├── winning_trades
│   ├── total_pnl
│   └── ...
└── KPISyncWorker (background)
    └── Every 30s: POST /api/bots/{bot_id}/kpi/update
        └── Backend Database (persisted)
```

### Data Flow

```
Trade Execution
    ↓
LocalKPITracker.record_trade()
    ↓
Metrics updated in memory
    ↓
KPISyncWorker (every 30s)
    ↓
POST /api/bots/{bot_id}/kpi/update
    ↓
Backend persists to bot_kpis table
    ↓
GET /api/bots/{bot_id}/kpi returns latest metrics
```

## Running a Bot with KPI Syncing

### Environment Variables

To run a bot with KPI syncing enabled, set these environment variables:

```bash
# Required: Bot identifier (UUID of the bot instance)
export BOT_ID="779e0bc5-ee36-493e-9984-c15169675eb3"

# Optional: Backend API base URL (default: http://localhost:8000)
export API_BASE="http://localhost:8000"

# Optional: How often to sync KPIs in seconds (default: 30)
export KPI_SYNC_INTERVAL="30"

# Optional: Other bot config
export EXCHANGE_WS_URL="ws://engine:9001"
export STARTING_EQUITY="100000.0"
```

### Running Alpha Bot

**Local Development:**
```bash
cd /home/naitik/Desktop/opensoft-26/Synthetic-Bull

# Activate virtual environment
source .venv/bin/activate

# Set environment variables
export BOT_ID="779e0bc5-ee36-493e-9984-c15169675eb3"  # The Alpha-01 bot
export API_BASE="http://localhost:8000"
export EXCHANGE_WS_URL="ws://127.0.0.1:9001"  # Local engine

# Run bot
python -m alpha.main
```

**Expected Output:**
```
[AlphaBot] Starting KPI sync worker for bot 779e0bc5-ee36-493e-9984-c15169675eb3 (interval=30s)
[KPISyncWorker] KPISyncWorker started for bot 779e0bc5-ee36-493e-9984-c15169675eb3 (interval=30s, type=alpha)
[AlphaBot] Regime: random -> trending (H=0.582)
...
```

### Running Market Maker Bot

```bash
cd bots

# Set environment variables
export BOT_ID="your-mm-bot-id"
export API_BASE="http://localhost:8000"
export EXCHANGE_WS_URL="ws://engine:9001"

# Run MM bot
python -m market_maker.main
```

### Docker Deployment

In `docker-compose.yml`:

```yaml
services:
  alpha_bot:
    image: python:3.11-slim
    environment:
      - BOT_ID=779e0bc5-ee36-493e-9984-c15169675eb3
      - API_BASE=http://synthetic-bull-admin:8000
      - EXCHANGE_WS_URL=ws://engine:9001
      - KPI_SYNC_INTERVAL=30
    depends_on:
      - admin_api
      - engine

  market_maker_bot:
    image: python:3.11-slim
    environment:
      - BOT_ID=your-mm-bot-id
      - API_BASE=http://synthetic-bull-admin:8000
      - EXCHANGE_WS_URL=ws://engine:9001
      - KPI_SYNC_INTERVAL=30
    depends_on:
      - admin_api
      - engine
```

## API Endpoints for KPI Monitoring

### Get Current KPIs

```bash
# Get KPI data for a specific bot
curl http://localhost:8000/api/bots/{bot_id}/kpi

# Example response:
{
  "id": "e21d12ce-8e5f-47da-ba30-e535fa87dbb7",
  "bot_id": "779e0bc5-ee36-493e-9984-c15169675eb3",
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
    "consecutive_losses": 3
  },
  "updated_at": "2026-04-01T14:34:14"
}
```

### Manual KPI Update (for testing)

```bash
curl -X POST http://localhost:8000/api/bots/{bot_id}/kpi/update \
  -H "Content-Type: application/json" \
  -d '{
    "total_trades": 50,
    "winning_trades": 31,
    "losing_trades": 19,
    "total_pnl": 3100.00,
    "realized_pnl": 3000.00,
    "win_rate": 0.62,
    "max_drawdown": 0.085,
    "sharpe_ratio": 1.52
  }'
```

## KPI Metrics Explained

### Common KPIs (All Bots)

| Metric | Type | Description |
|--------|------|-------------|
| `total_trades` | int | Total number of trades executed |
| `winning_trades` | int | Number of profitable trades |
| `losing_trades` | int | Number of losing trades |
| `total_pnl` | float | Total profit/loss in currency |
| `realized_pnl` | float | P&L from closed positions |
| `unrealized_pnl` | float | P&L from open positions |
| `win_rate` | float | Percentage of winning trades (0.0-1.0) |
| `max_drawdown` | float | Maximum equity drawdown (0.0-1.0) |
| `sharpe_ratio` | float | Risk-adjusted return metric |

### Strategy-Specific Metrics

**Alpha Bot `strategy_metrics`:**
```json
{
  "trades": 45,
  "avg_trade_duration_minutes": 45,
  "profit_factor": 2.15,
  "consecutive_losses": 3
}
```

**Market Maker Bot `strategy_metrics`:**
```json
{
  "total_fills": 1500,
  "bid_fills": 750,
  "ask_fills": 750,
  "spread_pnl": 2350.75
}
```

## Configuration Details

### KPI Sync Interval

Controls how often bot metrics are pushed to backend:

```bash
# Sync every 15 seconds (more frequent updates)
export KPI_SYNC_INTERVAL="15"

# Sync every 60 seconds (less network overhead)
export KPI_SYNC_INTERVAL="60"
```

**Recommendation**: 30 seconds balances real-time visibility with network overhead.

### API Base URL

Ensure bots can reach the backend API:

```bash
# Local development
export API_BASE="http://localhost:8000"

# Docker internal network
export API_BASE="http://synthetic-bull-admin:8000"

# Remote deployment
export API_BASE="https://api.synthetic-bull.com"
```

## Monitoring KPI Syncing

### Check Sync Logs

Look for these messages in bot output:

```
[KPISyncWorker] KPISyncWorker started for bot 779e0bc5... (interval=30s, type=alpha)
[KPISyncWorker] KPI sync successful for bot 779e0bc5...
```

### Verify Sync is Working

```bash
# Record initial KPI value
BEFORE=$(curl -s http://localhost:8000/api/bots/{bot_id}/kpi | jq '.total_trades')
echo "Before: $BEFORE trades"

# Wait 35 seconds for sync to occur
sleep 35

# Check if updated
AFTER=$(curl -s http://localhost:8000/api/bots/{bot_id}/kpi | jq '.total_trades')
echo "After: $AFTER trades"

# Should show increase if bot executed trades
if [ "$AFTER" -gt "$BEFORE" ]; then
  echo "✓ KPI syncing is working!"
else
  echo "✗ KPI syncing may not be working"
fi
```

### Check API Logs

```bash
# View admin API logs for KPI updates
docker logs synthetic-bull-admin | grep -i kpi

# Example output:
INFO:     172.19.0.1:54502 - "POST /api/bots/779e0bc5.../kpi/update HTTP/1.1" 200 OK
```

## Troubleshooting

### KPIs Stay at Zero

**Cause**: Bot is running but no trades are being executed, or KPI syncer is not running.

**Solution**:
```bash
# 1. Check bot logs for KPI sync worker start message
# 2. Verify bot is executing trades (check status endpoint)
# 3. Verify BOT_ID environment variable is set correctly
# 4. Check API connectivity with manual update
```

### KPI Sync Fails

**Error in logs**: `KPI sync error for bot...`

**Common causes**:
1. API server unreachable - check `API_BASE` URL
2. Network connectivity - verify `EXCHANGE_WS_URL` and `API_BASE` are accessible
3. Bot ID doesn't exist - ensure bot is created before running bot process

**Solution**:
```bash
# Test API connectivity
curl -v http://localhost:8000/api/bots

# Test KPI update endpoint
curl -X POST http://localhost:8000/api/bots/{bot_id}/kpi/update \
  -H "Content-Type: application/json" \
  -d '{"total_trades": 1}'
```

### Updated_at Timestamp Not Changing

**Cause**: KPI syncer may not be calling the update endpoint.

**Solution**:
```bash
# 1. Check sync interval setting
echo $KPI_SYNC_INTERVAL

# 2. Verify bot logs show sync messages
# 3. Monitor with: curl in a loop
while true; do
  curl -s http://localhost:8000/api/bots/{bot_id}/kpi | jq '.updated_at'
  sleep 5
done
```

### Multiple Bots Same ID

**Cause**: All bots using same BOT_ID will update the same KPI record.

**Solution**: Each bot must have unique ID:
```bash
# Bot 1
export BOT_ID="779e0bc5-ee36-493e-9984-c15169675eb3"

# Bot 2
export BOT_ID="fb099923-adfc-459a-a445-c65571e6e90f"
```

## Integration Example

```python
# Your monitoring script
import requests
import time

BOT_ID = "779e0bc5-ee36-493e-9984-c15169675eb3"
API_BASE = "http://localhost:8000"

def monitor_bot():
    while True:
        response = requests.get(f"{API_BASE}/api/bots/{BOT_ID}/kpi")
        kpi = response.json()
        
        print(f"Bot Performance:")
        print(f"  Trades: {kpi['total_trades']}")
        print(f"  Win Rate: {kpi['win_rate']*100:.1f}%")
        print(f"  PnL: ${kpi['total_pnl']:,.2f}")
        print(f"  Sharpe: {kpi['sharpe_ratio']:.2f}")
        print(f"  Max DD: {kpi['max_drawdown']*100:.2f}%")
        print(f"  Updated: {kpi['updated_at']}")
        print()
        
        time.sleep(10)

if __name__ == "__main__":
    monitor_bot()
```

## Implementation Details

### File Structure

```
bots/
├── shared/
│   ├── kpi_syncer.py          # KPI sync logic (NEW)
│   └── config.py              # BOT_ID, API_BASE config (UPDATED)
├── alpha/
│   └── main.py                # Uses KPISyncWorker (UPDATED)
└── market_maker/
    └── main.py                # Uses KPISyncWorker (UPDATED)
```

### KPI Syncer Class

**`KPISyncWorker`**: Background async task that:
- Runs independently from main bot loop
- Extracts metrics from local tracker every N seconds
- Makes HTTP POST to `/api/bots/{bot_id}/kpi/update`
- Handles errors gracefully with logging

**`KPISyncer`**: Helper class that:
- Formats tracker data for API
- Handles HTTP requests
- Supports different tracker types (alpha, mm)

## Performance Impact

- **Network**: Single HTTP POST every 30s (~60 bytes)
- **CPU**: Negligible (background async task)
- **Memory**: Minimal overhead
- **Latency**: Non-blocking, won't affect trading

## Next Steps

1. **Deploy**: Run bots with `BOT_ID` and `API_BASE` set
2. **Monitor**: Watch KPI updates via API or UI
3. **Dashboard**: Use KPI data in frontend for real-time metrics
4. **Alerts**: Set up alerts when KPIs cross thresholds
