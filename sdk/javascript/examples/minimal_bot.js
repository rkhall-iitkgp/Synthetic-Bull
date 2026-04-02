import * as crypto from 'crypto';
import { SyntheticBullClient } from '../src/index.js';

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

async function main() {
  const bot = new MyBot();
  await bot.run();
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1].endsWith('minimal_bot.js')) {
  main().catch(console.error);
}
