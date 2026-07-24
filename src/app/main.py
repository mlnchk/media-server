"""Composition root for the dashboard and Telegram polling process."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI

from bot.handlers import BOT_COMMANDS, build_router
from dashboard.routes import router as dashboard_router

logger = logging.getLogger(__name__)


def load_allowed_user_ids(value: str | None = None) -> set[int]:
    raw = value if value is not None else os.getenv("ALLOWED_USER_IDS", "")
    try:
        ids = {int(item.strip()) for item in raw.split(",") if item.strip()}
    except ValueError as exc:
        raise RuntimeError("ALLOWED_USER_IDS must contain comma-separated numeric IDs") from exc
    if not ids:
        raise RuntimeError("ALLOWED_USER_IDS must contain at least one Telegram user ID")
    return ids


async def _poll(dispatcher: Dispatcher, bot: Bot) -> None:
    try:
        try:
            await bot.set_my_commands(BOT_COMMANDS)
        except Exception:
            logger.warning("Could not register Telegram bot commands", exc_info=True)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Telegram polling stopped unexpectedly; dashboard remains available")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task: asyncio.Task[None] | None = None
    bot: Bot | None = None
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        allowed = load_allowed_user_ids()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = Dispatcher()
        dispatcher.include_router(build_router(allowed))
        app.state.telegram_dispatcher = dispatcher
        task = asyncio.create_task(_poll(dispatcher, bot), name="telegram-polling")
    except Exception:
        logger.exception("Telegram bot could not start; dashboard remains available")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if bot is not None:
            await bot.session.close()


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
app = FastAPI(title="Media Dashboard", lifespan=lifespan)
app.include_router(dashboard_router)
