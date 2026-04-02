import { WebSocket } from 'ws';

export class SyntheticBullClient {
  constructor({
    wsUrl,
    apiKey = "",
    guestMode = false,
    autoReconnect = true,
    reconnectMinDelay = 1.0,
    reconnectMaxDelay = 30.0,
    heartbeatInterval = 15.0,
    symbolFilter = null,
    onMessage = null,
    onWelcome = null,
    onOrderbook = null,
    onTrade = null,
    onCandle = null,
    onPortfolio = null,
    onOpenOrders = null,
    onAck = null,
    onCancelAck = null,
    onSymbols = null,
    onError = null,
    onPong = null,
    onConnect = null,
    onDisconnect = null,
    onReconnect = null,
  }) {
    this.wsUrl = wsUrl;
    this.apiKey = apiKey;
    this.guestMode = guestMode;
    this.autoReconnect = autoReconnect;
    this.reconnectMinDelay = reconnectMinDelay;
    this.reconnectMaxDelay = reconnectMaxDelay;
    this.heartbeatInterval = heartbeatInterval;
    this.symbolFilter = symbolFilter ? new Set(symbolFilter) : null;

    // Callbacks
    this.onMessage = onMessage;
    this.onWelcome = onWelcome;
    this.onOrderbook = onOrderbook;
    this.onTrade = onTrade;
    this.onCandle = onCandle;
    this.onPortfolio = onPortfolio;
    this.onOpenOrders = onOpenOrders;
    this.onAck = onAck;
    this.onCancelAck = onCancelAck;
    this.onSymbols = onSymbols;
    this.onError = onError;
    this.onPong = onPong;
    this.onConnect = onConnect;
    this.onDisconnect = onDisconnect;
    this.onReconnect = onReconnect;

    // Internal state
    this._ws = null;
    this._sendQueue = [];
    this._stopEvent = false;
    this._firstConnectComplete = false;
    
    // Promises for waiting
    this._connectedPromise = this._createPromise();
    this._welcomedPromise = this._createPromise();

    this.userId = null;
    this.symbolPrices = {};
    this.shortSellingConfig = {};
    this.latestPortfolio = null;
    this.latestOpenOrders = [];
    
    this._keepaliveIntervalId = null;
    this._queueIntervalId = null;
  }

  _createPromise() {
    let resolve;
    const promise = new Promise((res) => {
      resolve = res;
    });
    return { promise, resolve };
  }

  _resetWaiters() {
    this._connectedPromise = this._createPromise();
    this._welcomedPromise = this._createPromise();
  }

  async runForever() {
    if (!this.guestMode && !this.apiKey) {
      throw new Error("apiKey is required unless guestMode=true");
    }

    let backoff = Math.max(this.reconnectMinDelay, 0.1);
    const maxBackoff = Math.max(this.reconnectMaxDelay, backoff);

    while (!this._stopEvent) {
      let disconnectReason = "connection closed";
      try {
        await new Promise((resolve, reject) => {
          this._ws = new WebSocket(this.wsUrl);
          
          this._ws.on('open', async () => {
            this._startLoopers();
            this._connectedPromise.resolve();
            await this._emit(this.onConnect, { type: "connect", ws_url: this.wsUrl });

            if (this.guestMode) {
              await this._sendNow({ type: "guest_login" });
            } else {
              await this._sendNow({ type: "auth", api_key: this.apiKey });
            }

            if (this._firstConnectComplete) {
              await this._emit(this.onReconnect, { type: "reconnect", ws_url: this.wsUrl });
            }
            this._firstConnectComplete = true;
            backoff = Math.max(this.reconnectMinDelay, 0.1);
          });

          this._ws.on('message', async (data) => {
            try {
              const msg = JSON.parse(data.toString());
              if (typeof msg !== 'object' || msg === null) return;
              await this._handleMessage(msg);
            } catch (exc) {
              await this._emit(this.onError, { type: "error", message: `message decode failure: ${exc.message}` });
            }
          });

          this._ws.on('close', (code, reason) => {
            disconnectReason = `WebSocket closed cleanly: code=${code} reason=${reason}`;
            resolve(); // Break inner promise to trigger reconnect logic
          });

          this._ws.on('error', (err) => {
            disconnectReason = err.message;
            reject(err);
          });
        });
      } catch (exc) {
        disconnectReason = exc.message || String(exc);
        if (!this.autoReconnect || this._stopEvent) {
          throw exc;
        }
      } finally {
        this._stopLoopers();
        this._ws = null;
        this._resetWaiters();
        await this._emit(
          this.onDisconnect,
          { type: "disconnect", reason: disconnectReason }
        );
      }

      if (!this.autoReconnect || this._stopEvent) {
        break;
      }

      await new Promise(res => setTimeout(res, backoff * 1000));
      backoff = Math.min(backoff * 2.0, maxBackoff);
    }
  }

  _startLoopers() {
    this._queueIntervalId = setInterval(async () => {
      while (this._sendQueue.length > 0) {
        const payload = this._sendQueue.shift();
        try {
          await this._sendNow(payload);
        } catch (e) {
          this._sendQueue.unshift(payload); // put back
          break;
        }
      }
    }, 10); // Check queue every 10ms

    if (this.heartbeatInterval > 0) {
      this._keepaliveIntervalId = setInterval(async () => {
        try {
          await this.send({ type: "ping" });
        } catch (e) {
          // ignore
        }
      }, this.heartbeatInterval * 1000);
    }
  }

  _stopLoopers() {
    if (this._queueIntervalId !== null) clearInterval(this._queueIntervalId);
    if (this._keepaliveIntervalId !== null) clearInterval(this._keepaliveIntervalId);
    this._queueIntervalId = null;
    this._keepaliveIntervalId = null;
  }

  async stop() {
    this._stopEvent = true;
    if (this._ws !== null) {
      this._ws.close();
    }
  }

  async close() {
    await this.stop();
  }

  start() {
    // Background the runForever execution.
    this.runForever().catch(console.error);
    return this;
  }

  async waitUntilConnected() {
    await this._connectedPromise.promise;
  }

  async waitUntilWelcome() {
    await this._welcomedPromise.promise;
  }

  async send(payload) {
    this._sendQueue.push(payload);
  }

  async placeLimit(symbol, side, price, qty) {
    await this.send({
      type: "place_order",
      symbol: symbol,
      order_type: "limit",
      side: side,
      price: Number(price.toFixed(2)),
      qty: Number(qty.toFixed(5)),
    });
  }

  async placeMarket(symbol, side, qty) {
    await this.send({
      type: "place_order",
      symbol: symbol,
      order_type: "market",
      side: side,
      qty: Number(qty.toFixed(5)),
    });
  }

  async cancel(symbol, orderId) {
    await this.send({
      type: "cancel_order",
      symbol: symbol,
      order_id: Number(orderId),
    });
  }

  async getSymbols() {
    await this.send({ type: "get_symbols" });
  }

  async deposit(botId, amount) {
    await this.send({ type: "deposit", bot_id: botId, amount: amount });
  }

  async ping() {
    await this.send({ type: "ping" });
  }

  async _sendNow(payload) {
    if (this._ws === null || this._ws.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket is not connected");
    }
    this._ws.send(JSON.stringify(payload));
  }

  async _handleMessage(msg) {
    const msgType = String(msg.type || "");

    if (["orderbook", "trade", "candle"].includes(msgType) && this.symbolFilter) {
      const symbol = String(msg.symbol || "");
      if (!this.symbolFilter.has(symbol)) {
        return;
      }
    }

    if (msgType === "welcome") {
      this.userId = msg.user_id;
      this.symbolPrices = {};
      if (Array.isArray(msg.symbols)) {
        for (const entry of msg.symbols) {
          if (entry && entry.symbol) {
            this.symbolPrices[entry.symbol] = Number(entry.price || 0.0);
          }
        }
      }
      this.shortSellingConfig = (typeof msg.short_selling === "object" && msg.short_selling !== null) ? msg.short_selling : {};
      this._welcomedPromise.resolve();
    }

    if (msgType === "portfolio") {
      this.latestPortfolio = msg;
    }

    if (msgType === "open_orders") {
      const orders = msg.orders || [];
      if (Array.isArray(orders)) {
        this.latestOpenOrders = orders.filter(o => typeof o === "object" && o !== null);
      }
    }

    await this._emit(this.onMessage, msg);

    if (msgType === "welcome") {
      await this._emit(this.onWelcome, msg);
    } else if (msgType === "orderbook") {
      await this._emit(this.onOrderbook, msg);
    } else if (msgType === "trade") {
      await this._emit(this.onTrade, msg);
    } else if (msgType === "candle") {
      await this._emit(this.onCandle, msg);
    } else if (msgType === "portfolio") {
      await this._emit(this.onPortfolio, msg);
    } else if (msgType === "open_orders") {
      await this._emit(this.onOpenOrders, msg);
    } else if (msgType === "ack") {
      await this._emit(this.onAck, msg);
    } else if (msgType === "cancel_ack") {
      await this._emit(this.onCancelAck, msg);
    } else if (msgType === "symbols") {
      await this._emit(this.onSymbols, msg);
    } else if (msgType === "error") {
      await this._emit(this.onError, msg);
    } else if (msgType === "pong") {
      await this._emit(this.onPong, msg);
    }
  }

  async _emit(handler, msg) {
    if (typeof handler !== 'function') {
      return;
    }
    try {
      const result = handler(msg);
      if (result instanceof Promise) {
        await result;
      }
    } catch (exc) {
      console.error(`[SyntheticBullClient] Handler error for '${msg.type || "unknown"}': ${exc.message}`);
    }
  }
}
