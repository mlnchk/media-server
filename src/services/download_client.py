"""Transmission-backed download operations with provider-neutral results."""

from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


class DownloadClientError(RuntimeError):
    """The download client operation failed."""


@dataclass(frozen=True)
class AddDownloadResult:
    id: int | None
    name: str
    duplicate: bool


@dataclass(frozen=True)
class DownloadStatus:
    id: int
    name: str
    status: str
    downloaded_bytes: int
    total_bytes: int
    remaining_bytes: int
    rate_bytes: int
    eta_seconds: int | None
    percent_complete: float


_STATUS_NAMES = {
    0: "stopped", 1: "queued to verify", 2: "verifying", 3: "queued to download",
    4: "downloading", 5: "queued to seed", 6: "seeding",
}
_UNKNOWN_ETA = {-1, -2}
_FIELDS = [
    "id", "name", "status", "downloadedEver", "totalSize", "leftUntilDone",
    "rateDownload", "eta", "percentDone", "downloadDir", "files",
]


class _TransmissionRpcClient:
    def __init__(self, timeout: float = 20) -> None:
        self.url = os.getenv("TRANSMISSION_RPC_URL", "http://transmission:9091/transmission/rpc")
        self.username = os.getenv("USER_NAME", "")
        self.password = os.getenv("USER_PASS", "")
        self.timeout = timeout
        self.session_id: str | None = None

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        headers = {"Content-Type": "application/json"}
        if self.session_id:
            headers["X-Transmission-Session-Id"] = self.session_id
        try:
            return requests.post(
                self.url, json=payload, headers=headers,
                auth=(self.username, self.password) if self.username else None,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DownloadClientError(f"Could not contact download client: {exc}") from exc

    def call(self, method: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._post({"method": method, "arguments": arguments})
        if response.status_code == 409:
            self.session_id = response.headers.get("X-Transmission-Session-Id")
            if not self.session_id:
                raise DownloadClientError("Download client did not provide a session ID")
            response = self._post({"method": method, "arguments": arguments})
        try:
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DownloadClientError(f"Download client RPC failed: {exc}") from exc
        if data.get("result") != "success":
            raise DownloadClientError(f"Download client RPC error: {data.get('result', 'unknown')}")
        return data.get("arguments", {})

    def add(self, payload: bytes) -> AddDownloadResult:
        if not payload:
            raise DownloadClientError("The torrent payload is empty")
        arguments = self.call("torrent-add", {"metainfo": base64.b64encode(payload).decode("ascii")})
        duplicate = "torrent-duplicate" in arguments
        torrent = arguments.get("torrent-duplicate" if duplicate else "torrent-added")
        if not isinstance(torrent, dict):
            raise DownloadClientError("Download client returned no torrent details")
        return AddDownloadResult(torrent.get("id"), str(torrent.get("name") or "Unknown torrent"), duplicate)

    def torrents(self) -> list[dict[str, Any]]:
        torrents = self.call("torrent-get", {"fields": _FIELDS}).get("torrents", [])
        return torrents if isinstance(torrents, list) else []


def _normalize(raw: dict[str, Any]) -> DownloadStatus:
    total = max(0, int(raw.get("totalSize") or 0))
    downloaded = max(0, int(raw.get("downloadedEver") or 0))
    remaining = max(0, int(raw.get("leftUntilDone") or max(total - downloaded, 0)))
    rate = max(0, int(raw.get("rateDownload") or 0))
    eta_raw = int(raw.get("eta") if raw.get("eta") is not None else -1)
    eta = None if eta_raw in _UNKNOWN_ETA or eta_raw < 0 else eta_raw
    if eta is None and remaining and rate:
        eta = remaining // rate
    percent_raw = raw.get("percentDone")
    percent = float(percent_raw) * 100 if percent_raw is not None else (downloaded / total * 100 if total else 0)
    return DownloadStatus(
        id=int(raw.get("id") or 0), name=str(raw.get("name") or "Unknown download"),
        status=_STATUS_NAMES.get(int(raw.get("status") or 0), "unknown"),
        downloaded_bytes=downloaded, total_bytes=total, remaining_bytes=remaining,
        rate_bytes=rate, eta_seconds=eta, percent_complete=min(100.0, max(0.0, percent)),
    )


async def add_download(payload: bytes) -> AddDownloadResult:
    return await asyncio.to_thread(_TransmissionRpcClient().add, payload)


async def list_downloads() -> list[DownloadStatus]:
    raw = await asyncio.to_thread(_TransmissionRpcClient().torrents)
    return [_normalize(item) for item in raw]


def path_belongs_to_active_download(path: Path) -> bool:
    """Return true when path overlaps content of a non-stopped Transmission torrent."""
    source = path.resolve()
    for torrent in _TransmissionRpcClient().torrents():
        if int(torrent.get("status") or 0) == 0:
            continue
        root = Path(str(torrent.get("downloadDir") or "")).resolve()
        candidates = [root / str(file.get("name") or "") for file in torrent.get("files", [])]
        if not candidates:
            candidates = [root / str(torrent.get("name") or "")]
        for candidate in candidates:
            candidate = candidate.resolve()
            if source == candidate or source in candidate.parents or candidate in source.parents:
                return True
    return False
