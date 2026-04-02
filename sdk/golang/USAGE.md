# Synthetic-Bull Go SDK Usage Guide

This guide explains how to use the Go SDK to build and run bots against the Synthetic-Bull exchange.

## 1. Prerequisites

- Go 1.22+
- Running Synthetic-Bull backend:
  - WebSocket engine at `ws://127.0.0.1:9001`
  - Admin API at `http://127.0.0.1:8000`

## 2. Use The SDK In This Repository

For local development from this repo:

```bash
cd sdk/golang
go mod tidy
```

## 3. Create A Bot API Key

```go
package main

import (
    "fmt"
    sdk "synthetic-bull-sdk-go/syntheticbullsdk"
)

func main() {
    admin := sdk.NewAdminApiClient("http://127.0.0.1:8000")
    bot, err := admin.CreateBot("my-go-strategy-bot")
    if err != nil {
        panic(err)
    }
    fmt.Println("BOT_ID:", bot["id"])
    fmt.Println("BOT_API_KEY:", bot["api_key"])
}
```

Save this key in your environment as `BOT_API_KEY`.

## 4. Minimal Custom Bot

See `examples/minimal_bot/main.go`.

Run it:

```bash
cd sdk/golang
go run ./examples/minimal_bot
```

## 5. Core Client Methods

- `PlaceLimit(symbol, side, price, qty)`
- `PlaceMarket(symbol, side, qty)`
- `Cancel(symbol, orderID)`
- `GetSymbols()`
- `Deposit(botID, amount)`
- `Ping()`
- `WaitUntilConnected()`
- `WaitUntilWelcome()`
- `Stop()`

## 6. Event Hooks You Can Use

Set handlers in `ClientConfig`:

- `OnMessage`
- `OnWelcome`
- `OnOrderbook`
- `OnTrade`
- `OnCandle`
- `OnPortfolio`
- `OnOpenOrders`
- `OnAck`
- `OnCancelAck`
- `OnSymbols`
- `OnError`
- `OnPong`
- `OnConnect`
- `OnDisconnect`
- `OnReconnect`

## 7. Docker Notes

Inside Docker network, set:

- `EXCHANGE_WS_URL=ws://engine:9001`
- `ADMIN_API_URL=http://admin_api:8000`

## 8. Troubleshooting

- `Invalid API key`:
  - Ensure the bot was created via Admin API and key is copied exactly.
- Cannot connect to exchange:
  - Check engine service and URL.
- No trades happen:
  - Verify symbol exists and bot has enough balance/permissions.
  - Check `OnError` callback logs for rejections.
- Bot reconnect behavior:
  - Use `OnReconnect` to cancel stale orders or rebuild strategy state.
