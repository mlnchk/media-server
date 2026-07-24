"""Authorized Telegram controllers over shared media capabilities."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets
from collections import OrderedDict
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.download_client import DownloadClientError, add_download, list_downloads
from services.library import (
    LibraryError, LibraryLocation, library_areas, list_library_items,
    move_library_item, rename_library_item, resolve_location,
)
from services.media import conversion_status, get_audio_tracks, start_audio_conversion
from services.media_server import MediaServerError, refresh_libraries
from services.torrent_indexer import (
    TorrentIndexerLoginError, TorrentResult, fetch_torrent, search_torrents,
)

logger = logging.getLogger(__name__)
_URL = re.compile(r"(?i)^(?:https?://|www\.|letterboxd\.com/)")
_MAX_SEARCHES_PER_USER = 10
_MAX_SELECTIONS_PER_USER = 100

BOT_COMMANDS = [
    BotCommand(command="start", description="Show help and available commands"),
    BotCommand(command="downloads", description="Show download progress"),
    BotCommand(command="library", description="Browse and manage the media library"),
    BotCommand(command="refresh", description="Request a Jellyfin library refresh"),
]


@dataclass(frozen=True)
class _Action:
    kind: str
    location: LibraryLocation
    value: str = ""


def parse_search_text(text: str | None) -> tuple[str | None, str | None]:
    value = (text or "").strip()
    if not value:
        return None, "Send a movie title."
    if _URL.match(value):
        return None, "Links are not supported. Send the movie title instead."
    return value, None


def _size(value: int) -> str:
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return "unknown"


def _eta(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}h {minutes:02d}m" if hours else f"{minutes:d}m {secs:02d}s"


async def _edit_if_changed(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Telegram rejects edits whose text and keyboard have not changed."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).casefold():
            return False
        raise


def build_router(allowed_user_ids: set[int]) -> Router:
    router = Router()
    searches: dict[int, OrderedDict[str, list[TorrentResult]]] = {}
    selections: dict[int, OrderedDict[str, LibraryLocation]] = {}
    actions: dict[int, OrderedDict[str, _Action]] = {}
    awaiting_rename: dict[int, LibraryLocation] = {}

    def authorized(user_id: int | None) -> bool:
        return user_id is not None and user_id in allowed_user_ids

    def remember(store: dict[int, OrderedDict], user_id: int, value: object, maximum: int) -> str:
        token = secrets.token_hex(4)
        values = store.setdefault(user_id, OrderedDict())
        values[token] = value
        while len(values) > maximum:
            values.popitem(last=False)
        return token

    async def deny_callback(callback: CallbackQuery) -> bool:
        if authorized(callback.from_user.id):
            return False
        await callback.answer("Not authorized", show_alert=True)
        return True

    async def show_downloads(message: Message) -> None:
        try:
            items = await list_downloads()
        except DownloadClientError:
            logger.exception("Could not list downloads")
            await _edit_if_changed(message, "Could not contact the download client.")
            return
        lines = ["<b>Downloads</b>"]
        if not items:
            lines.append("No downloads.")
        for item in items[:20]:
            lines.append(
                f"\n<b>{html.escape(item.name)}</b>\n{html.escape(item.status)} · "
                f"{item.percent_complete:.1f}% · {_size(item.downloaded_bytes)} / {_size(item.total_bytes)}\n"
                f"remaining {_size(item.remaining_bytes)} · {_size(item.rate_bytes)}/s · ETA {_eta(item.eta_seconds)}"
            )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Refresh", callback_data="downloads")
        ]])
        await _edit_if_changed(message, "\n".join(lines), reply_markup=keyboard)

    async def render_location(message: Message, location: LibraryLocation | None = None) -> None:
        user_id = message.chat.id
        if location is None:
            buttons = []
            for area in library_areas():
                token = remember(selections, user_id, LibraryLocation(area), _MAX_SELECTIONS_PER_USER)
                buttons.append([InlineKeyboardButton(text=area.title(), callback_data=f"lib:{token}")])
            await message.edit_text("<b>Library</b>\nChoose an area:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            return
        try:
            items = await asyncio.to_thread(list_library_items, location.area, location.path)
        except LibraryError as exc:
            await message.edit_text(f"Could not browse library: {html.escape(str(exc))}")
            return
        lines = [f"<b>{html.escape(location.area.title())}</b> / {html.escape(location.path)}"]
        buttons = []
        if location.path:
            parent = location.path.rpartition("/")[0]
            token = remember(selections, user_id, LibraryLocation(location.area, parent), _MAX_SELECTIONS_PER_USER)
            buttons.append([InlineKeyboardButton(text="⬆️ Up", callback_data=f"lib:{token}")])
        for item in items[:30]:
            token = remember(selections, user_id, item.location, _MAX_SELECTIONS_PER_USER)
            icon = "📁" if item.is_dir else "📄"
            buttons.append([InlineKeyboardButton(text=f"{icon} {item.name}"[:60], callback_data=f"lib:{token}")])
        if location.path:
            current = remember(selections, user_id, location, _MAX_SELECTIONS_PER_USER)
            buttons.append([InlineKeyboardButton(text="Actions for this folder", callback_data=f"manage:{current}")])
        buttons.append([InlineKeyboardButton(text="Areas", callback_data="library")])
        if len(items) > 30:
            lines.append(f"Showing 30 of {len(items)} items.")
        await message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @router.message(Command("start", "help"))
    async def help_command(message: Message) -> None:
        if not authorized(message.from_user.id if message.from_user else None):
            await message.answer("You are not authorized to use this bot.")
            return
        await message.answer(
            "<b>Media bot</b>\n\n"
            "Send a movie title to search the torrent indexer.\n"
            "/downloads — show download progress\n"
            "/library — browse and manage media files\n"
            "/refresh — request a Jellyfin library refresh"
        )

    @router.message(Command("downloads"))
    async def downloads_command(message: Message) -> None:
        if not authorized(message.from_user.id if message.from_user else None):
            await message.answer("You are not authorized to use this bot.")
            return
        progress = await message.answer("Loading downloads…")
        await show_downloads(progress)

    @router.callback_query(F.data == "downloads")
    async def downloads_callback(callback: CallbackQuery) -> None:
        if await deny_callback(callback): return
        await callback.answer("Refreshing…")
        if callback.message: await show_downloads(callback.message)

    @router.message(Command("library"))
    async def library_command(message: Message) -> None:
        if not authorized(message.from_user.id if message.from_user else None):
            await message.answer("You are not authorized to use this bot.")
            return
        progress = await message.answer("Loading library…")
        await render_location(progress)

    @router.callback_query(F.data == "library")
    async def library_callback(callback: CallbackQuery) -> None:
        if await deny_callback(callback): return
        await callback.answer()
        if callback.message: await render_location(callback.message)

    @router.callback_query(F.data.startswith("lib:") | F.data.startswith("manage:"))
    async def select_library_item(callback: CallbackQuery) -> None:
        if await deny_callback(callback): return
        token = (callback.data or "").partition(":")[2]
        location = selections.get(callback.from_user.id, {}).get(token)
        if location is None:
            await callback.answer("This selection has expired.", show_alert=True); return
        try:
            path = await asyncio.to_thread(resolve_location, location)
        except LibraryError as exc:
            await callback.answer(str(exc), show_alert=True); return
        await callback.answer()
        if callback.message is None: return
        if path.is_dir() and (callback.data or "").startswith("lib:"):
            await render_location(callback.message, location); return
        buttons = []
        if path.is_file():
            inspect_action = remember(actions, callback.from_user.id, _Action("inspect", location), _MAX_SELECTIONS_PER_USER)
            buttons.append([InlineKeyboardButton(text="Inspect audio", callback_data=f"act:{inspect_action}")])
        for area in library_areas():
            if area != location.area:
                action = remember(actions, callback.from_user.id, _Action("move_confirm", location, area), _MAX_SELECTIONS_PER_USER)
                buttons.append([InlineKeyboardButton(text=f"Move to {area.title()}", callback_data=f"act:{action}")])
        rename = remember(actions, callback.from_user.id, _Action("rename_prompt", location), _MAX_SELECTIONS_PER_USER)
        buttons.append([InlineKeyboardButton(text="Rename", callback_data=f"act:{rename}")])
        await callback.message.edit_text(
            f"<b>{html.escape(path.name)}</b>\n{html.escape(location.area)} / {html.escape(location.path)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    @router.callback_query(F.data.startswith("act:"))
    async def library_action(callback: CallbackQuery) -> None:
        if await deny_callback(callback): return
        token = (callback.data or "").partition(":")[2]
        action = actions.get(callback.from_user.id, {}).get(token)
        if action is None:
            await callback.answer("This action has expired.", show_alert=True); return
        if callback.message is None: return
        if action.kind == "inspect":
            await callback.answer("Inspecting…")
            try:
                path = await asyncio.to_thread(resolve_location, action.location)
                tracks = await asyncio.to_thread(get_audio_tracks, path)
            except LibraryError as exc:
                await callback.message.edit_text(html.escape(str(exc))); return
            lines = [f"<b>Audio: {html.escape(path.name)}</b>"]
            dts = []
            for track in tracks:
                marker = " ⚠️ DTS" if track.is_dts else ""
                lines.append(f"Track {track.index}: {html.escape(track.codec.upper())} · {track.channels}ch{marker}")
                if track.is_dts: dts.append(track.index)
            keyboard = None
            if dts:
                conversion = remember(actions, callback.from_user.id, _Action("convert_confirm", action.location, ",".join(map(str, dts))), _MAX_SELECTIONS_PER_USER)
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Convert DTS tracks to AC3", callback_data=f"act:{conversion}")
                ]])
            await callback.message.edit_text("\n".join(lines) if tracks else "No audio tracks found.", reply_markup=keyboard)
        elif action.kind in {"move_confirm", "convert_confirm"}:
            await callback.answer()
            verb = f"move this item to {action.value.title()}" if action.kind == "move_confirm" else "convert all DTS tracks to AC3"
            confirmed = remember(actions, callback.from_user.id, _Action(action.kind.replace("_confirm", "_run"), action.location, action.value), _MAX_SELECTIONS_PER_USER)
            await callback.message.edit_text(
                f"Confirm: {html.escape(verb)}?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Confirm", callback_data=f"act:{confirmed}")],
                    [InlineKeyboardButton(text="Cancel", callback_data="library")],
                ]),
            )
        elif action.kind == "move_run":
            await callback.answer("Moving…")
            try:
                await asyncio.to_thread(move_library_item, action.location, LibraryLocation(action.value))
            except LibraryError as exc:
                logger.exception("Library move failed")
                await callback.message.edit_text(f"Move failed: {html.escape(str(exc))}")
            else:
                await callback.message.edit_text("Item moved successfully.")
        elif action.kind == "rename_prompt":
            awaiting_rename[callback.from_user.id] = action.location
            await callback.answer()
            await callback.message.edit_text("Send the new name. The rename will still require confirmation.")
        elif action.kind == "rename_run":
            await callback.answer("Renaming…")
            try:
                await asyncio.to_thread(rename_library_item, action.location, action.value)
            except LibraryError as exc:
                await callback.message.edit_text(f"Rename failed: {html.escape(str(exc))}")
            else:
                await callback.message.edit_text("Item renamed successfully.")
        elif action.kind == "convert_run":
            if conversion_status.running:
                await callback.answer("Another conversion is running.", show_alert=True); return
            await callback.answer("Starting conversion…")
            path = await asyncio.to_thread(resolve_location, action.location)
            task = start_audio_conversion(path, [int(value) for value in action.value.split(",")])
            if task is None:
                await callback.message.edit_text("Another conversion is already running."); return
            await callback.message.edit_text("Conversion started. The original is kept unless conversion succeeds.")
            task.add_done_callback(lambda done: logger.error("Conversion task failed", exc_info=done.exception()) if not done.cancelled() and done.exception() else None)

    @router.message(Command("refresh"))
    async def refresh_command(message: Message) -> None:
        if not authorized(message.from_user.id if message.from_user else None):
            await message.answer("You are not authorized to use this bot."); return
        progress = await message.answer("Requesting media library refresh…")
        try:
            await refresh_libraries()
        except MediaServerError:
            logger.exception("Media server refresh failed")
            await progress.edit_text("The media server did not accept the refresh request.")
        else:
            await progress.edit_text("Media library refresh requested.")

    @router.callback_query(F.data.startswith("cancel:"))
    async def cancel(callback: CallbackQuery) -> None:
        if await deny_callback(callback): return
        token = (callback.data or "").partition(":")[2]
        values = searches.get(callback.from_user.id, {})
        if token not in values:
            await callback.answer("This selection has expired.", show_alert=True); return
        values.pop(token, None)
        if callback.message: await callback.message.edit_text("Search cancelled.")
        await callback.answer()

    @router.callback_query(F.data.startswith("download:"))
    async def download(callback: CallbackQuery) -> None:
        if await deny_callback(callback): return
        try:
            _, token, raw_index = (callback.data or "").split(":", 2)
            choice = searches[callback.from_user.id][token][int(raw_index)]
        except (ValueError, KeyError, IndexError):
            await callback.answer("This selection has expired.", show_alert=True); return
        await callback.answer("Adding to download client…")
        try:
            result = await add_download(await fetch_torrent(choice.reference))
        except (DownloadClientError, Exception):
            logger.exception("Failed to fetch/add torrent %s", choice.reference)
            if callback.message: await callback.message.edit_text("Could not add the torrent. Please try again.")
            return
        searches.get(callback.from_user.id, {}).pop(token, None)
        status = "Already in download client" if result.duplicate else "Added to download client"
        if callback.message: await callback.message.edit_text(f"{status}:\n{html.escape(result.name)}")

    @router.message()
    async def search_or_rename(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        if not authorized(user_id):
            await message.answer("You are not authorized to use this bot."); return
        assert user_id is not None
        if user_id in awaiting_rename:
            location = awaiting_rename.pop(user_id)
            name = (message.text or "").strip()
            action = remember(actions, user_id, _Action("rename_run", location, name), _MAX_SELECTIONS_PER_USER)
            await message.answer(
                f"Rename to <b>{html.escape(name)}</b>?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Confirm", callback_data=f"act:{action}")],
                    [InlineKeyboardButton(text="Cancel", callback_data="library")],
                ]),
            ); return
        query, error = parse_search_text(message.text)
        if error:
            await message.answer(error); return
        assert query is not None
        progress = await message.answer(f"Searching torrent indexer for “{html.escape(query)}”…")
        try:
            results = await search_torrents(query, limit=3)
        except TorrentIndexerLoginError:
            logger.exception("Torrent indexer login failed")
            await progress.edit_text("Torrent indexer login failed. Check its configured credentials."); return
        except Exception:
            logger.exception("Torrent search failed for %r", query)
            await progress.edit_text("Torrent search failed. Please try again later."); return
        if not results:
            await progress.edit_text("No eligible results found (up to 30 GiB, no 4K/HDR)."); return
        token = remember(searches, user_id, results, _MAX_SEARCHES_PER_USER)
        lines = [f"Results for <b>{html.escape(query)}</b>:"]
        buttons = []
        for index, result in enumerate(results):
            lines.append(f"\n<b>{index + 1}. {html.escape(result.title)}</b>\n{result.size_gib:.2f} GiB · seeders {result.seeders} · leechers {result.leechers}")
            buttons.append([InlineKeyboardButton(text=f"Download {index + 1}", callback_data=f"download:{token}:{index}")])
        buttons.append([InlineKeyboardButton(text="Cancel", callback_data=f"cancel:{token}")])
        await progress.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    return router
