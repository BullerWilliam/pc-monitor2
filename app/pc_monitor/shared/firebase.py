from __future__ import annotations

from typing import Any

import requests


class FirebaseRegistry:
    def __init__(self, database_url: str, auth_token: str = "") -> None:
        self.database_url = database_url.rstrip("/")
        self.auth_token = auth_token

    def _url(self, path: str) -> str:
        suffix = f"{path}.json"
        if self.auth_token:
            return f"{self.database_url}/{suffix}?auth={self.auth_token}"
        return f"{self.database_url}/{suffix}"

    def put_pairing(self, pairing_code: str, payload: dict[str, Any]) -> None:
        requests.put(self._url(f"pairings/{pairing_code}"), json=payload, timeout=6).raise_for_status()

    def patch_pairing(self, pairing_code: str, payload: dict[str, Any]) -> None:
        requests.patch(self._url(f"pairings/{pairing_code}"), json=payload, timeout=6).raise_for_status()

    def fetch_pairing(self, pairing_code: str) -> dict[str, Any] | None:
        response = requests.get(self._url(f"pairings/{pairing_code}"), timeout=6)
        response.raise_for_status()
        return response.json()
