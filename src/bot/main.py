import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .handlers import build_router


def load_allowed_user_ids(value: str | None = None) -> set[int]:
    raw = value if value is not None else os.getenv("ALLOWED_USER_IDS", "")
    try:
        ids = {int(item.strip()) for item in raw.split(",") if item.strip()}
    except ValueError as exc:
        raise RuntimeError("ALLOWED_USER_IDS must be a comma-separated list of Telegram numeric IDs") from exc
    if not ids:
        raise RuntimeError("ALLOWED_USER_IDS must contain at least one Telegram user ID")
    return ids


async def run() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(load_allowed_user_ids()))
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
