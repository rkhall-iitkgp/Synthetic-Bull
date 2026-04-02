from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AdminApiError(RuntimeError):
    pass


@dataclass
class AdminApiClient:
    base_url: str = "http://127.0.0.1:8000"
    timeout: float = 10.0

    def create_bot(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/api/bots", body={"name": name})

    def list_bots(self, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        return self._request("GET", "/api/bots", params={"skip": skip, "limit": limit})

    def get_bot(self, bot_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/bots/{bot_id}")

    def get_trades(
        self,
        bot_id: str,
        skip: int = 0,
        limit: int = 100,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/bots/{bot_id}/trades",
            params={"skip": skip, "limit": limit, "session_id": session_id},
        )

    def get_portfolio(self, bot_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/bots/{bot_id}/portfolio")

    def get_kpi(self, bot_id: str, session_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/bots/{bot_id}/kpi",
            params={"session_id": session_id},
        )

    def deposit(self, bot_id: str, amount: float) -> dict[str, Any]:
        return self._request("POST", f"/api/bots/{bot_id}/deposit", body={"amount": amount})

    def start_session(self, bot_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/bots/{bot_id}/sessions/start")

    def stop_session(self, bot_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/bots/{bot_id}/sessions/stop")

    def list_sessions(
        self,
        bot_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/bots/{bot_id}/sessions",
            params={"skip": skip, "limit": limit},
        )

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        base = self.base_url.rstrip("/")
        url = f"{base}{path}"

        if params:
            cleaned = {k: v for k, v in params.items() if v is not None}
            if cleaned:
                url = f"{url}?{urlencode(cleaned)}"

        headers = {"Accept": "application/json"}
        data: bytes | None = None

        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        request = Request(url=url, method=method.upper(), headers=headers, data=data)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                if not raw.strip():
                    return None
                return json.loads(raw)
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise AdminApiError(f"{exc.code} {exc.reason}: {details}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", "unknown error")
            raise AdminApiError(f"Unable to reach admin API at {url}: {reason}") from exc
