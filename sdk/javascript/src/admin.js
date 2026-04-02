class AdminApiError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AdminApiError';
  }
}

export class AdminApiClient {
  constructor({ baseUrl = "http://127.0.0.1:8000", timeout = 10000 } = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeout = timeout;
  }

  async _request(method, path, body = null, params = null) {
    let url = `${this.baseUrl}${path}`;

    if (params) {
      const cleaned = Object.fromEntries(
        Object.entries(params).filter(([_, v]) => v != null)
      );
      if (Object.keys(cleaned).length > 0) {
        url += `?${new URLSearchParams(cleaned).toString()}`;
      }
    }

    const headers = { 'Accept': 'application/json' };
    const options = {
      method: method.toUpperCase(),
      headers,
      signal: AbortSignal.timeout(this.timeout)
    };

    if (body !== null) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }

    try {
      const response = await fetch(url, options);
      if (!response.ok) {
        const text = await response.text();
        throw new AdminApiError(`${response.status} ${response.statusText}: ${text}`);
      }
      const text = await response.text();
      if (!text.trim()) {
        return null;
      }
      return JSON.parse(text);
    } catch (exc) {
      if (exc instanceof AdminApiError) {
        throw exc;
      }
      throw new AdminApiError(`Unable to reach admin API at ${url}: ${exc.message}`);
    }
  }

  async createBot(name) {
    return this._request("POST", "/api/bots", { name });
  }

  async listBots(skip = 0, limit = 100) {
    return this._request("GET", "/api/bots", null, { skip, limit });
  }

  async getBot(botId) {
    return this._request("GET", `/api/bots/${botId}`);
  }

  async getTrades(botId, skip = 0, limit = 100, sessionId = null) {
    return this._request("GET", `/api/bots/${botId}/trades`, null, { skip, limit, session_id: sessionId });
  }

  async getPortfolio(botId) {
    return this._request("GET", `/api/bots/${botId}/portfolio`);
  }

  async getKpi(botId, sessionId = null) {
    return this._request("GET", `/api/bots/${botId}/kpi`, null, { session_id: sessionId });
  }

  async deposit(botId, amount) {
    return this._request("POST", `/api/bots/${botId}/deposit`, { amount });
  }

  async startSession(botId) {
    return this._request("POST", `/api/bots/${botId}/sessions/start`);
  }

  async stopSession(botId) {
    return this._request("POST", `/api/bots/${botId}/sessions/stop`);
  }

  async listSessions(botId, skip = 0, limit = 100) {
    return this._request("GET", `/api/bots/${botId}/sessions`, null, { skip, limit });
  }
}
