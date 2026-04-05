"""Devin API v1 client for the orchestrator.

v1 endpoints (base: https://api.devin.ai/v1):
  POST /sessions                     — create session
  GET  /sessions/{session_id}        — get session details
  GET  /sessions                     — list sessions
  POST /sessions/{session_id}/message — send message
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests

from orchestrator.config import get_config
from orchestrator.models import SessionInfo


class DevinAPIError(Exception):
    """Raised when a Devin API call fails."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Devin API error {status_code}: {message}")


class DevinClient:
    """Thin wrapper around the Devin API v1."""

    _MAX_RETRIES = 5
    _BACKOFF_BASE = 3  # seconds

    def __init__(self) -> None:
        config = get_config()
        self._base_url = config.DEVIN_BASE_URL.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {config.DEVIN_API_KEY}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_session(
        self,
        prompt: str,
        structured_output_schema: dict | None = None,
        tags: list[str] | None = None,
        max_acu_limit: int | None = None,
    ) -> tuple[str, str]:
        """Create a new Devin session and return ``(session_id, session_url)``."""

        body: dict[str, Any] = {"prompt": prompt}
        if structured_output_schema is not None:
            body["structured_output_schema"] = structured_output_schema
        if tags is not None:
            body["tags"] = tags
        if max_acu_limit is not None:
            body["max_acu_limit"] = max_acu_limit

        data = self._request("POST", "/sessions", json=body)
        return data["session_id"], data["url"]

    def get_session(self, session_id: str) -> SessionInfo:
        """Fetch the current state of a session."""

        data = self._request("GET", f"/sessions/{session_id}")
        return self._parse_session(data)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        """Execute an HTTP request with retry-on-429 and error handling."""

        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            self._log(f"{method} {url} (attempt {attempt})")

            resp = requests.request(
                method,
                url,
                headers=self._headers,
                json=json,
                params=params,
                timeout=60,
            )

            if resp.status_code == 429:
                wait = min(self._BACKOFF_BASE ** attempt, 60)
                self._log(f"Rate-limited (429), retrying in {wait}s")
                last_exc = DevinAPIError(429, "rate limited")
                time.sleep(wait)
                continue

            if not resp.ok:
                raise DevinAPIError(resp.status_code, resp.text)

            # Some endpoints return 204 / empty body.
            if resp.status_code == 204 or not resp.content:
                return {}

            return resp.json()

        # Exhausted all retries on 429.
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _parse_session(data: dict) -> SessionInfo:
        """Convert a raw API response dict into a ``SessionInfo``."""

        # v1 API returns "pull_request" (singular, nullable object), not a list.
        pr = data.get("pull_request")
        pull_requests = [pr] if pr else []

        return SessionInfo(
            session_id=data["session_id"],
            status=data.get("status_enum") or data.get("status", "unknown"),
            pull_requests=pull_requests,
            structured_output=data.get("structured_output"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    @staticmethod
    def _log(message: str) -> None:
        """Print a timestamped log line to stdout."""

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[DevinClient {ts}] {message}")
