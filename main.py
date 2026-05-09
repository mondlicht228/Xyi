"""
main.py — Точка входа. Инициализация бота, диспетчера и роутеров.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from admin import admin_router
from stant import user_router

# ─────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────
BOT_TOKEN = "ВАШ_ТОКЕН_ЗДЕСЬ"          # @BotFather

# ─────────────────────────────────────────
# ЛОГИРОВАНИЕ
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Подключаем роутеры
    dp.include_router(admin_router)   # Сначала — чтобы админ-хендлеры имели приоритет
    dp.include_router(user_router)

    logger.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
