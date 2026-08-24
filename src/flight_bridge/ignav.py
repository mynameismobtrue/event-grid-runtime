"""Minimal authenticated Ignav transport. Responses stay in memory only."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .core import classify_provider_response

BASE_URL = "https://ignav.com/api"


@dataclass(frozen=True)
class ProviderResult:
    status: str
    http_status: int | None
    payload: Any | None


class IgnavClient:
    def __init__(self, api_key: str, transport: Callable[..., tuple[int, bytes]] | None = None):
        self._api_key = api_key.strip()
        self._transport = transport or self._urlopen

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def build_open_jaw_query(self, origin: str, outbound_date: str, return_destination: str) -> dict[str, Any]:
        return {
            "legs": [
                {"origin": origin, "destination": "LIS", "departure_date": outbound_date, "max_stops": 1},
                {"origin": "LIS", "destination": return_destination, "departure_date": "2026-11-03", "max_stops": 1},
            ],
            "adults": 1,
            "cabin_class": "economy",
            "market": "BR",
            "allow_self_transfer": False,
            "airlines_exclude": ["DT"],
        }

    def _urlopen(self, method: str, path: str, body: dict[str, Any] | None) -> tuple[int, bytes]:
        encoded = json.dumps(body).encode() if body is not None else None
        request = Request(
            BASE_URL + path,
            data=encoded,
            method=method,
            headers={"X-Api-Key": self._api_key, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:  # nosec B310: fixed HTTPS base URL
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()
        except URLError:
            return 0, b""

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> ProviderResult:
        if not self.configured:
            return ProviderResult("AUTH_REQUIRED", None, None)
        status, raw = self._transport(method, path, body)
        try:
            payload = json.loads(raw.decode()) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        return ProviderResult(classify_provider_response(status if status else None, payload), status or None, payload)

    def health_check(self) -> ProviderResult:
        return self.request("GET", "/airports?q=GRU&limit=1")

    def search(self, origin: str, outbound_date: str, return_destination: str) -> ProviderResult:
        return self.request("POST", "/fares/search", self.build_open_jaw_query(origin, outbound_date, return_destination))
