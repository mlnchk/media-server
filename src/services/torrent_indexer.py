"""RuTracker-backed torrent discovery and metadata retrieval."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from py_rutracker import AsyncRuTrackerClient

MAX_SIZE_BYTES = 30 * 1024**3
_HIGH_END = re.compile(
    r"(?i)(?:\b2160p?\b|\b4k\b|\buhd\b|\bhdr(?:10\+?)?\b|dolby[ ._-]*vision|(?<![a-z])dv(?![a-z]))"
)
_PREFERRED_HD = re.compile(r"(?i)(?:\b1080[pi]?\b|\bfull[ ._-]*hd\b|\bbluray\b|\bblu[ ._-]*ray\b|\bhd\b)")


class TorrentIndexerError(RuntimeError):
    """The torrent indexer operation failed."""


class TorrentIndexerLoginError(TorrentIndexerError):
    """Credentials or CAPTCHA prevented indexer login."""


@dataclass(frozen=True)
class TorrentResult:
    reference: int
    title: str
    size: int
    seeders: int
    leechers: int
    url: str
    added: str = ""

    @property
    def size_gib(self) -> float:
        return self.size / 1024**3

    # Compatibility for presentation code and old callers.
    @property
    def topic_id(self) -> int:
        return self.reference

    @property
    def seeds(self) -> int:
        return self.seeders

    @property
    def leeches(self) -> int:
        return self.leechers

    @property
    def topic_url(self) -> str:
        return self.url


class _RutrackerClient:
    def __init__(self) -> None:
        self.username = os.getenv("RUTRACKER_USERNAME", "")
        self.password = os.getenv("RUTRACKER_PASSWORD", "")
        self.client: AsyncRuTrackerClient | None = None

    async def __aenter__(self) -> "_RutrackerClient":
        if not self.username or not self.password:
            raise TorrentIndexerLoginError("Torrent indexer credentials are not configured")
        self.client = AsyncRuTrackerClient(login=self.username, password=self.password)
        try:
            await self.client.init()
        except Exception as exc:
            await self._close()
            raise _indexer_exception(exc, login=True) from exc
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._close()

    async def _close(self) -> None:
        if self.client is not None:
            try:
                await self.client.close()
            finally:
                self.client = None

    async def search(self, query: str) -> list[TorrentResult]:
        assert self.client is not None
        try:
            raw = await self.client.search_all_pages(title=query, max_pages=2)
            return [
                TorrentResult(
                    reference=int(item.topic_id),
                    title=str(item.title),
                    size=_size_to_bytes(item.size, item.unit),
                    seeders=int(item.seedmed or 0),
                    leechers=int(item.leechmed or 0),
                    added=str(item.added or ""),
                    url=f"https://rutracker.org/forum/viewtopic.php?t={item.topic_id}",
                )
                for item in raw
            ]
        except Exception as exc:
            raise _indexer_exception(exc) from exc

    async def fetch(self, reference: int) -> bytes:
        assert self.client is not None
        try:
            content = await self.client.download(reference)
            if not content:
                raise TorrentIndexerError("Torrent indexer returned an empty file")
            return content
        except TorrentIndexerError:
            raise
        except Exception as exc:
            raise _indexer_exception(exc) from exc


def _eligible(result: TorrentResult) -> bool:
    return 0 < result.size <= MAX_SIZE_BYTES and not _HIGH_END.search(result.title)


def _rank(results: list[TorrentResult], limit: int) -> list[TorrentResult]:
    return sorted(
        (result for result in results if _eligible(result)),
        key=lambda result: (
            -result.seeders,
            -bool(_PREFERRED_HD.search(result.title)),
            abs(result.size_gib - 10),
            result.title.casefold(),
        ),
    )[:limit]


async def search_torrents(query: str, limit: int = 10) -> list[TorrentResult]:
    query = query.strip()
    if not query:
        return []
    async with _RutrackerClient() as client:
        return _rank(await client.search(query), limit)


async def fetch_torrent(reference: int) -> bytes:
    async with _RutrackerClient() as client:
        return await client.fetch(reference)


def _size_to_bytes(size: float, unit: str | None) -> int:
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(float(size) * multipliers.get((unit or "GB").upper(), 1024**3))


def _indexer_exception(exc: Exception, login: bool = False) -> TorrentIndexerError:
    message = str(exc)
    if login or any(word in message.casefold() for word in ("captcha", "login", "auth", "password")):
        return TorrentIndexerLoginError(
            "Torrent indexer login failed. Check its credentials and solve any CAPTCHA in a browser."
        )
    return TorrentIndexerError(f"Torrent indexer request failed: {message}")
