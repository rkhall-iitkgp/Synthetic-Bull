# Synthetic-Bull SDK Usage Guide

This guide explains how to use the Python SDK to build and run bots against the Synthetic-Bull exchange.

## 1. Prerequisites

- Python 3.10+
- Running Synthetic-Bull backend:
  - WebSocket engine at `ws://127.0.0.1:9001`
  - Admin API at `http://127.0.0.1:8000`

On Windows, prefer `127.0.0.1` instead of `localhost` for local services.

## 2. Install The SDK

From the repository root:

```bash
pip install -e ./sdk/python
```

## 3. Create A Bot API Key

Use the Admin API helper:

```python
from synthetic_bull_sdk import AdminApiClient

admin = AdminApiClient(base_url="http://127.0.0.1:8000")
bot = admin.create_bot("my-strategy-bot")
print("BOT_ID:", bot["id"])
print("BOT_API_KEY:", bot["api_key"])
```

Save this key in your environment as `BOT_API_KEY`.

## 4. Minimal Custom Bot

```python
import asyncio
import os

from synthetic_bull_sdk import SyntheticBullClient


class MyBot:
    def __init__(self) -> None:
        self.symbol = os.getenv("BOT_SYMBOL", "AAPL")
        self.sent_order = False
        self.client = SyntheticBullClient(
            ws_url=os.getenv("EXCHANGE_WS_URL", "ws://127.0.0.1:9001"),
            api_key=os.getenv("BOT_API_KEY", ""),
            on_welcome=self.on_welcome,
            on_orderbook=self.on_orderbook,
            on_ack=self.on_ack,
            on_error=self.on_error,
        )

    async def on_welcome(self, msg: dict) -> None:
        print("Connected as", msg.get("user_id"))

    async def on_orderbook(self, msg: dict) -> None:
        if msg.get("symbol") != self.symbol or self.sent_order:
            return
        mid = float(msg.get("mid", 0.0))
        if mid <= 0:
            return
        await self.client.place_limit(self.symbol, "buy", mid * 0.999, 0.01)
        self.sent_order = True

    async def on_ack(self, msg: dict) -> None:
        print("Order accepted", msg)

    async def on_error(self, msg: dict) -> None:
        print("Exchange error", msg.get("message"))

    async def run(self) -> None:
        await self.client.run_forever()


async def main() -> None:
    await MyBot().run()


if __name__ == "__main__":
    asyncio.run(main())
```

## 5. Core Client Methods

- `place_limit(symbol, side, price, qty)`
- `place_market(symbol, side, qty)`
- `cancel(symbol, order_id)`
- `get_symbols()`
- `deposit(bot_id, amount)` (admin-authenticated connection)
- `ping()`
- `wait_until_connected()`
- `wait_until_welcome()`
- `stop()`

## 6. Event Hooks You Can Use

Pass these handlers to `SyntheticBullClient(...)`:

- `on_message`
- `on_welcome`
- `on_orderbook`
- `on_trade`
- `on_candle`
- `on_portfolio`
- `on_open_orders`
- `on_ack`
- `on_cancel_ack`
- `on_symbols`
- `on_error`
- `on_pong`
- `on_connect`
- `on_disconnect`
- `on_reconnect`

## 7. Run Existing Alpha/MM Bots (Now SDK-Based)

The project bots now use this SDK directly.

Run alpha:

```powershell
$env:BOT_API_KEY="<alpha-api-key>"
$env:BOT_SYMBOL="AAPL"
$env:BOT_STATUS_PORT="3001"
$env:EXCHANGE_WS_URL="ws://127.0.0.1:9001"
python -m alpha.main
```

Run market maker:

```powershell
$env:BOT_API_KEY="<mm-api-key>"
$env:BOT_SYMBOL="AAPL"
$env:BOT_STATUS_PORT="3002"
$env:EXCHANGE_WS_URL="ws://127.0.0.1:9001"
python -m market_maker.main
```

## 8. Run Multiple Alpha Copies

Use separate terminals with different keys and status ports.

Terminal 1:

```powershell
$env:BOT_API_KEY="<alpha-key-1>"
$env:BOT_STATUS_PORT="3001"
$env:BOT_SYMBOL="AAPL"
python -m alpha.main
```

Terminal 2:

```powershell
$env:BOT_API_KEY="<alpha-key-2>"
$env:BOT_STATUS_PORT="3011"
$env:BOT_SYMBOL="TSLA"
python -m alpha.main
```

You can also copy the alpha package folder and run it as a new module, as long as you set unique env vars.

## 9. Docker Notes

Inside Docker network, set:

- `EXCHANGE_WS_URL=ws://engine:9001`
- `ADMIN_API_URL=http://admin_api:8000` (if needed by your script)

## 10. Troubleshooting

- `Invalid API key`:
  - Make sure the bot was created via Admin API and key is copied exactly.
- Cannot connect to exchange:
  - Check engine service and URL.
  - On local Windows runs, use `ws://127.0.0.1:9001`.
- No trades happen:
  - Verify symbol exists and bot has enough balance/permissions.
  - Check `error` callback logs for rejections.
- Bot reconnect behavior:
  - Use `on_reconnect` to cancel old orders or rebuild strategy state.
