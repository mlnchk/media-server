"""RuTracker search, filtering, ranking, download, and Transmission handoff."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass

from py_rutracker import AsyncRuTrackerClient

from .transmission import AddTorrentResult, TransmissionClient

MAX_SIZE_BYTES = 30 * 1024**3
_HIGH_END = re.compile(
    r"(?i)(?:\b2160p?\b|\b4k\b|\buhd\b|\bhdr(?:10\+?)?\b|dolby[ ._-]*vision|(?<![a-z])dv(?![a-z]))"
)
_PREFERRED_HD = re.compile(r"(?i)(?:\b1080[pi]?\b|\bfull[ ._-]*hd\b|\bbluray\b|\bblu[ ._-]*ray\b|\bhd\b)")


class RutrackerError(RuntimeError):
    """A RuTracker operation failed."""


class RutrackerLoginError(RutrackerError):
    """Credentials or CAPTCHA prevented RuTracker login."""


@dataclass(frozen=True)
class TorrentResult:
    topic_id: int
    title: str
    size: int
    seeds: int
    leeches: int
    topic_url: str
    added: str = ""

    @property
    def size_gib(self) -> float:
        return self.size / 1024**3


class RutrackerClient:
    def __init__(self, username: str | None = None, password: str | None = None) -> None:
        self.username = username if username is not None else os.getenv("RUTRACKER_USERNAME", "")
        self.password = password if password is not None else os.getenv("RUTRACKER_PASSWORD", "")
        self.client: AsyncRuTrackerClient | None = None

    async def __aenter__(self) -> "RutrackerClient":
        if not self.username or not self.password:
            raise RutrackerLoginError("RuTracker username and password are not configured")
        self.client = AsyncRuTrackerClient(login=self.username, password=self.password)
        try:
            await self.client.init()
        except Exception as exc:
            await self._close()
            raise _rutracker_exception(exc, login=True) from exc
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._close()

    async def _close(self) -> None:
        if self.client is not None:
            try:
                await self.client.close()
            finally:
                self.client = None

    async def search(self, query: str, max_pages: int = 2) -> list[TorrentResult]:
        if self.client is None:
            raise RuntimeError("RuTracker client is not open")
        try:
            raw_results = await self.client.search_all_pages(
                title=query, max_pages=min(max(max_pages, 1), 2)
            )
            return [
                TorrentResult(
                    topic_id=int(item.topic_id),
                    title=str(item.title),
                    size=_size_to_bytes(item.size, item.unit),
                    seeds=int(item.seedmed or 0),
                    leeches=int(item.leechmed or 0),
                    added=str(item.added or ""),
                    topic_url=f"https://rutracker.org/forum/viewtopic.php?t={item.topic_id}",
                )
                for item in raw_results
            ]
        except Exception as exc:
            raise _rutracker_exception(exc) from exc

    async def download(self, topic_id: int) -> bytes:
        if self.client is None:
            raise RuntimeError("RuTracker client is not open")
        try:
            data = await self.client.download(topic_id)
            if not data:
                raise RutrackerError("RuTracker returned an empty torrent file")
            return data
        except RutrackerError:
            raise
        except Exception as exc:
            raise _rutracker_exception(exc) from exc


def is_eligible(result: TorrentResult) -> bool:
    return 0 < result.size <= MAX_SIZE_BYTES and not _HIGH_END.search(result.title)


def rank_results(results: list[TorrentResult], limit: int = 3) -> list[TorrentResult]:
    """Seeders dominate; preferred HD and moderate size break ties."""
    eligible = (result for result in results if is_eligible(result))
    return sorted(
        eligible,
        key=lambda result: (
            -result.seeds,
            -bool(_PREFERRED_HD.search(result.title)),
            abs(result.size_gib - 10),
            result.title.casefold(),
        ),
    )[:limit]


async def search_torrents(query: str, limit: int = 3) -> list[TorrentResult]:
    query = query.strip()
    if not query:
        return []
    async with RutrackerClient() as client:
        return rank_results(await client.search(query, max_pages=2), limit=limit)


async def download_torrent(topic_id: int) -> bytes:
    async with RutrackerClient() as client:
        return await client.download(topic_id)


async def add_torrent(topic_id: int, transmission: TransmissionClient | None = None) -> AddTorrentResult:
    torrent_data = await download_torrent(topic_id)
    client = transmission or TransmissionClient()
    return await asyncio.to_thread(client.add_torrent_file, torrent_data)


def _size_to_bytes(size: float, unit: str | None) -> int:
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(float(size) * multipliers.get((unit or "GB").upper(), 1024**3))


def _rutracker_exception(exc: Exception, login: bool = False) -> RutrackerError:
    message = str(exc)
    if login or any(word in message.casefold() for word in ("captcha", "login", "auth", "password")):
        return RutrackerLoginError(
            "RuTracker login failed. Check RUTRACKER_USERNAME/RUTRACKER_PASSWORD and solve any CAPTCHA in a browser."
        )
    return RutrackerError(f"RuTracker request failed: {message}")
