from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from alpha.config import ALPHA_BOT_PORT

_state: dict = {
    "equity": 100000.0,
    "pnl": 0.0,
    "realizedPnl": 0.0,
    "unrealizedPnl": 0.0,
    "position": "FLAT",
    "trades": 0,
    "winRate": 0.0,
    "sharpe": 0.0,
    "maxDrawdown": 0.0,
    "halted": False,
}

app = FastAPI(title="Alpha Bot Status")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/bot/status")
async def bot_status() -> dict:
    return _state


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "bot": "alpha", "port": ALPHA_BOT_PORT}


def update_status(new_state: dict):
    _state.update(new_state)


async def run():
    config = uvicorn.Config(app=app, host="0.0.0.0", port=ALPHA_BOT_PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
