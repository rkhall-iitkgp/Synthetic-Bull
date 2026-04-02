import asyncio
import os

from synthetic_bull_sdk import SyntheticBullClient


class MinimalBot:
    def __init__(self) -> None:
        self.symbol = os.getenv("BOT_SYMBOL", "AAPL")
        self.order_sent = False
        self.client = SyntheticBullClient(
            ws_url=os.getenv("EXCHANGE_WS_URL", "ws://127.0.0.1:9001"),
            api_key=os.getenv("BOT_API_KEY", ""),
            on_welcome=self.on_welcome,
            on_orderbook=self.on_orderbook,
            on_ack=self.on_ack,
            on_error=self.on_error,
        )

    async def on_welcome(self, msg: dict) -> None:
        print(f"[MinimalBot] Connected as {msg.get('user_id')}")
        await self.client.get_symbols()

    async def on_orderbook(self, msg: dict) -> None:
        if msg.get("symbol") != self.symbol:
            return
        if self.order_sent:
            return

        mid = float(msg.get("mid", 0.0))
        if mid <= 0:
            return

        # Demo strategy: place one passive buy at 0.1% below mid.
        bid = mid * 0.999
        await self.client.place_limit(self.symbol, "buy", bid, 0.01)
        self.order_sent = True

    async def on_ack(self, msg: dict) -> None:
        print(f"[MinimalBot] Order accepted: {msg}")

    async def on_error(self, msg: dict) -> None:
        print(f"[MinimalBot] Exchange error: {msg.get('message')}")

    async def run(self) -> None:
        await self.client.run_forever()


async def main() -> None:
    bot = MinimalBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
