"""Authorized, in-memory Telegram search and selection handlers."""

from __future__ import annotations

import html
import logging
import re
import secrets

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.torrents import RutrackerLoginError, TorrentResult, add_torrent, search_torrents
from services.transmission import TransmissionError

logger = logging.getLogger(__name__)
_URL = re.compile(r"(?i)^(?:https?://|www\.|letterboxd\.com/)")
_MAX_SEARCHES_PER_USER = 10


def parse_search_text(text: str | None) -> tuple[str | None, str | None]:
    value = (text or "").strip()
    if not value:
        return None, "Send a movie title."
    if _URL.match(value):
        return None, "Links are not supported. Send the movie title instead."
    return value, None


def build_router(allowed_user_ids: set[int]) -> Router:
    router = Router()
    # Each rendered result list gets its own token. This keeps buttons tied to
    # the search that created them rather than to the user's latest search.
    pending: dict[int, dict[str, list[TorrentResult]]] = {}

    def authorized(user_id: int | None) -> bool:
        return user_id is not None and user_id in allowed_user_ids

    @router.callback_query(F.data.startswith("cancel:"))
    async def cancel(callback: CallbackQuery) -> None:
        if not authorized(callback.from_user.id):
            await callback.answer("Not authorized", show_alert=True)
            return
        token = (callback.data or "").partition(":")[2]
        user_searches = pending.get(callback.from_user.id, {})
        if token not in user_searches:
            await callback.answer("This selection has expired.", show_alert=True)
            return
        user_searches.pop(token, None)
        if not user_searches:
            pending.pop(callback.from_user.id, None)
        if callback.message:
            await callback.message.edit_text("Search cancelled.")
        await callback.answer()

    @router.callback_query(F.data == "cancel")
    async def expired_legacy_cancel(callback: CallbackQuery) -> None:
        await callback.answer("This selection has expired.", show_alert=True)

    @router.callback_query(F.data.startswith("download:"))
    async def download(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id
        if not authorized(user_id):
            await callback.answer("Not authorized", show_alert=True)
            return
        try:
            _, token, raw_index = (callback.data or "").split(":", 2)
            index = int(raw_index)
            choice = pending[user_id][token][index]
        except (ValueError, KeyError, IndexError):
            await callback.answer("This selection has expired.", show_alert=True)
            return
        await callback.answer("Adding to Transmission…")
        try:
            result = await add_torrent(choice.topic_id)
        except TransmissionError:
            logger.exception("Transmission rejected topic %s", choice.topic_id)
            if callback.message:
                await callback.message.edit_text(
                    "Transmission could not add the torrent. Check the bot container logs."
                )
            return
        except Exception:
            logger.exception("Failed to fetch/add RuTracker topic %s", choice.topic_id)
            if callback.message:
                await callback.message.edit_text(
                    "Could not download the torrent from RuTracker. Please try again."
                )
            return
        user_searches = pending.get(user_id, {})
        user_searches.pop(token, None)
        if not user_searches:
            pending.pop(user_id, None)
        status = "Already in Transmission" if result.duplicate else "Added to Transmission"
        if callback.message:
            await callback.message.edit_text(f"{status}:\n{html.escape(result.name)}")

    @router.message()
    async def search(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not authorized(user_id):
            await message.answer("You are not authorized to use this bot.")
            return
        query, error = parse_search_text(message.text)
        if error:
            await message.answer(error)
            return
        assert query is not None and user_id is not None
        progress = await message.answer(f'Searching RuTracker for “{html.escape(query)}”…')
        try:
            results = await search_torrents(query, limit=3)
        except RutrackerLoginError:
            logger.exception("RuTracker login failed")
            await progress.edit_text(
                "RuTracker login failed. Check the configured credentials and solve any CAPTCHA in a browser."
            )
            return
        except Exception:
            logger.exception("RuTracker search failed for %r", query)
            await progress.edit_text("RuTracker search failed. Please try again later.")
            return
        if not results:
            await progress.edit_text("No eligible results found (up to 30 GiB, no 4K/HDR).")
            return
        token = secrets.token_hex(4)
        user_searches = pending.setdefault(user_id, {})
        user_searches[token] = results
        while len(user_searches) > _MAX_SEARCHES_PER_USER:
            user_searches.pop(next(iter(user_searches)))
        lines = [f"Results for <b>{html.escape(query)}</b>:"]
        buttons = []
        for index, result in enumerate(results):
            lines.append(
                f"\n<b>{index + 1}. {html.escape(result.title)}</b>\n"
                f"{result.size_gib:.2f} GiB · seeders {result.seeds} · leechers {result.leeches}"
            )
            buttons.append([InlineKeyboardButton(
                text=f"Download {index + 1}", callback_data=f"download:{token}:{index}"
            )])
        buttons.append([InlineKeyboardButton(text="Cancel", callback_data=f"cancel:{token}")])
        await progress.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    return router
