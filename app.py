import asyncio
import logging
import os
from analytics import Analytics
from analytics_middleware import FunnelMiddleware
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import SimpleEventIsolation
from database import Database
from handlers import common_router, registration_router, admin_router, user_router, giveaway_router
from scheduling import scheduler_enabled, start_scheduler
from utils import sync_templates_to_db

# Включаем логирование всех ошибок
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def create_dispatcher(db, bot, admin_ids, analytics=None):
    """Build routing without starting polling, scheduler or database initialization."""
    dp = Dispatcher(events_isolation=SimpleEventIsolation())
    dp['db'] = db
    dp['admin_ids'] = admin_ids
    dp['bot'] = bot
    dp['analytics'] = analytics
    dp.message.middleware(FunnelMiddleware())
    dp.callback_query.middleware(FunnelMiddleware())
    dp.include_router(common_router)
    dp.include_router(registration_router)
    dp.include_router(user_router)
    dp.include_router(giveaway_router)
    dp.include_router(admin_router)
    return dp


async def main():
    from config import load_config

    config = load_config()
    enable_scheduler = scheduler_enabled()
    db = Database(config.db_path)

    # Синхронизируем шаблоны из Obsidian-файлов в базу данных
    sync_templates_to_db(db)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    # Separate journal: no changes to business tables or Database migrations.
    analytics = (Analytics(config.db_path + '.analytics.sqlite')
                 if os.getenv('FUNNEL_ANALYTICS_ENABLED', '0') == '1' else None)
    dp = create_dispatcher(db, bot, config.admin_ids, analytics)

    scheduler = start_scheduler(bot, db, config.admin_ids, config.channel_id,
                                enabled=enable_scheduler)
    try:
        print("Бот Разумбой запущен...")
        for admin_id in config.admin_ids:
            try:
                await bot.send_message(admin_id, "✅ Бот запущен и готов к работе!")
            except Exception:
                pass
        await dp.start_polling(bot)
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
