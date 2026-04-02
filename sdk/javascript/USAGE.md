# Synthetic-Bull JavaScript SDK Usage Guide

This guide explains how to use the JavaScript SDK to build and run bots against the Synthetic-Bull exchange.

## 1. Prerequisites

- Node.js 18+
- Running Synthetic-Bull backend:
  - WebSocket engine at `ws://127.0.0.1:9001`
  - Admin API at `http://127.0.0.1:8000`

On Windows, prefer `127.0.0.1` instead of `localhost` for local services.

## 2. Install The SDK

From the repository root:

```bash
cd sdk/javascript
npm install
```

## 3. Create A Bot API Key

Use the Admin API helper:

```javascript
import { AdminApiClient } from './src/index.js';

async function setup() {
  const admin = new AdminApiClient({ baseUrl: "http://127.0.0.1:8000" });
  const bot = await admin.createBot("my-strategy-bot");
  console.log("BOT_ID:", bot.id);
  console.log("BOT_API_KEY:", bot.api_key);
}
setup();
```

Save this key in your environment as `BOT_API_KEY`.

## 4. Minimal Custom Bot

```javascript
import { SyntheticBullClient } from './src/index.js';

class MyBot {
  constructor() {
    this.symbol = process.env.BOT_SYMBOL || "AAPL";
    this.sentOrder = false;

    this.client = new SyntheticBullClient({
      wsUrl: process.env.EXCHANGE_WS_URL || "ws://127.0.0.1:9001",
      apiKey: process.env.BOT_API_KEY || "",
      onWelcome: this.onWelcome.bind(this),
      onOrderbook: this.onOrderbook.bind(this),
      onAck: this.onAck.bind(this),
      onError: this.onError.bind(this)
    });
  }

  async onWelcome(msg) {
    console.log("Connected as", msg.user_id);
  }

  async onOrderbook(msg) {
    if (msg.symbol !== this.symbol || this.sentOrder) {
      return;
    }
    const mid = Number(msg.mid || 0.0);
    if (mid <= 0) {
      return;
    }
    await this.client.placeLimit(this.symbol, "buy", mid * 0.999, 0.01);
    this.sentOrder = true;
  }

  async onAck(msg) {
    console.log("Order accepted", msg);
  }

  async onError(msg) {
    console.log("Exchange error", msg.message);
  }

  async run() {
    await this.client.runForever();
  }
}

const bot = new MyBot();
bot.run().catch(console.error);
```

## 5. Core Client Methods

- `client.placeLimit(symbol, side, price, qty)`
- `client.placeMarket(symbol, side, qty)`
- `client.cancel(symbol, orderId)`
- `client.getSymbols()`
- `client.deposit(botId, amount)` (admin-authenticated connection)
- `client.ping()`
- `client.waitUntilConnected()`
- `client.waitUntilWelcome()`
- `client.stop()`

## 6. Event Hooks You Can Use

Pass these handlers to `new SyntheticBullClient({ ... })`:

- `onMessage`
- `onWelcome`
- `onOrderbook`
- `onTrade`
- `onCandle`
- `onPortfolio`
- `onOpenOrders`
- `onAck`
- `onCancelAck`
- `onSymbols`
- `onError`
- `onPong`
- `onConnect`
- `onDisconnect`
- `onReconnect`

## 7. Troubleshooting

- `Invalid API key`:
  - Make sure the bot was created via Admin API and key is copied exactly.
- Cannot connect to exchange:
  - Check engine service and URL.
  - On local Windows runs, use `ws://127.0.0.1:9001`.
- No trades happen:
  - Verify symbol exists and bot has enough balance/permissions.
  - Check `error` callback logs for rejections.
- Bot reconnect behavior:
  - Use `onReconnect` to cancel old orders or rebuild strategy state.
