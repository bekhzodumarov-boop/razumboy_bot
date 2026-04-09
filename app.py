import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from config import load_config
from database import Database
from handlers import common_router, registration_router, admin_router, user_router

# Включаем логирование всех ошибок
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    config = load_config()
    db = Database(config.db_path)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    dp["db"] = db
    dp["admin_ids"] = config.admin_ids
    dp["bot"] = bot

    dp.include_router(common_router)
    dp.include_router(registration_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    print("Бот Разумбой запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
