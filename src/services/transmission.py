"""Narrow adapter for the Transmission JSON-RPC API."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

import requests


class TransmissionError(RuntimeError):
    """Transmission could not accept an RPC request."""


@dataclass(frozen=True)
class AddTorrentResult:
    id: int | None
    name: str
    duplicate: bool


class TransmissionClient:
    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 20,
    ) -> None:
        self.url = url or os.getenv(
            "TRANSMISSION_RPC_URL", "http://transmission:9091/transmission/rpc"
        )
        self.username = username if username is not None else os.getenv("USER_NAME", "")
        self.password = password if password is not None else os.getenv("USER_PASS", "")
        self.timeout = timeout
        self.session_id: str | None = None

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        headers = {"Content-Type": "application/json"}
        if self.session_id:
            headers["X-Transmission-Session-Id"] = self.session_id
        try:
            return requests.post(
                self.url,
                json=payload,
                headers=headers,
                auth=(self.username, self.password) if self.username else None,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TransmissionError(f"Could not contact Transmission: {exc}") from exc

    def _call(self, method: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._post({"method": method, "arguments": arguments})
        if response.status_code == 409:
            self.session_id = response.headers.get("X-Transmission-Session-Id")
            if not self.session_id:
                raise TransmissionError("Transmission did not provide an RPC session ID")
            response = self._post({"method": method, "arguments": arguments})
        try:
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransmissionError(f"Transmission RPC failed: {exc}") from exc
        if data.get("result") != "success":
            raise TransmissionError(f"Transmission RPC error: {data.get('result', 'unknown')}")
        return data.get("arguments", {})

    def add_torrent_file(self, torrent_bytes: bytes) -> AddTorrentResult:
        if not torrent_bytes:
            raise TransmissionError("The downloaded torrent file is empty")
        arguments = self._call(
            "torrent-add",
            {"metainfo": base64.b64encode(torrent_bytes).decode("ascii")},
        )
        duplicate = "torrent-duplicate" in arguments
        torrent = arguments.get("torrent-duplicate" if duplicate else "torrent-added")
        if not isinstance(torrent, dict):
            raise TransmissionError("Transmission returned no torrent details")
        return AddTorrentResult(
            id=torrent.get("id"),
            name=str(torrent.get("name") or "Unknown torrent"),
            duplicate=duplicate,
        )
