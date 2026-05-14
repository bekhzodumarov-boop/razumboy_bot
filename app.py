import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import load_config
from database import Database
from handlers import common_router, registration_router, admin_router, user_router, giveaway_router
from handlers.giveaway import check_giveaway_schedule, send_friday_winner_reminders
from handlers.admin import auto_remind_day_before, auto_remind_day_of

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
    dp.include_router(user_router)
    dp.include_router(giveaway_router)
    dp.include_router(admin_router)

    # ── APScheduler: проверка расписания розыгрыша каждую минуту ──
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(
        check_giveaway_schedule,
        trigger="cron",
        minute="*",          # каждую минуту
        args=[bot, db, config.admin_ids, config.channel_id],
    )
    # Пятничная рассылка победителям розыгрыша — каждый четверг в 21:10
    scheduler.add_job(
        send_friday_winner_reminders,
        trigger="cron",
        day_of_week="thu",
        hour=21,
        minute=10,
        args=[bot, db, config.admin_ids],
    )
    # Авторассылка за день до игры — ежедневно в 10:00
    scheduler.add_job(
        auto_remind_day_before,
        trigger="cron",
        hour=10,
        minute=0,
        args=[bot, db, config.admin_ids],
    )
    # Авторассылка в день игры — ежедневно в 10:00
    scheduler.add_job(
        auto_remind_day_of,
        trigger="cron",
        hour=10,
        minute=0,
        args=[bot, db, config.admin_ids],
    )
    scheduler.start()
    logger.info("APScheduler запущен — проверка расписания розыгрыша каждую минуту")

    print("Бот Разумбой запущен...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
