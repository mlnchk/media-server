"""Jellyfin-backed media library refresh operation."""

from __future__ import annotations

import asyncio
import os

import requests


class MediaServerError(RuntimeError):
    """The media server did not accept an operation."""


def _refresh() -> None:
    base_url = os.getenv("JELLYFIN_URL", "http://jellyfin:8096").rstrip("/")
    api_key = os.getenv("JELLYFIN_API_KEY", "").strip()
    if not api_key:
        raise MediaServerError("Media server API key is not configured")
    try:
        response = requests.post(
            f"{base_url}/Library/Refresh",
            headers={"X-Emby-Token": api_key},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MediaServerError(f"Media server did not accept the refresh request: {exc}") from exc


async def refresh_libraries() -> None:
    """Request a scan; successful return means accepted, not completed."""
    await asyncio.to_thread(_refresh)
