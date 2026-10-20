"""Optional scheduled jobs; registration and analytics do not depend on this module."""
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from handlers.giveaway import check_giveaway_schedule, send_friday_winner_reminders
from handlers.admin import auto_remind_day_before, auto_remind_day_of, auto_remind_day_of_followup

logger = logging.getLogger(__name__)


def scheduler_enabled():
    value = os.getenv('SCHEDULER_ENABLED', '1').strip()
    if value not in {'0', '1'}:
        raise ValueError('SCHEDULER_ENABLED must be 0 or 1')
    return value == '1'


def start_scheduler(bot, db, admin_ids, channel_id, *, enabled=True):
    if not enabled:
        logger.info('APScheduler disabled (SCHEDULER_ENABLED=0)')
        return None

    scheduler = AsyncIOScheduler(timezone='Asia/Tashkent')
    scheduler.add_job(check_giveaway_schedule, trigger='cron', minute='*',
                      args=[bot, db, admin_ids, channel_id])
    scheduler.add_job(send_friday_winner_reminders, trigger='cron', day_of_week='thu',
                      hour=21, minute=10, args=[bot, db, admin_ids])
    scheduler.add_job(auto_remind_day_before, trigger='cron', hour=10, minute=0,
                      args=[bot, db, admin_ids])
    scheduler.add_job(auto_remind_day_of, trigger='cron', hour=10, minute=0,
                      args=[bot, db, admin_ids])
    for hour in (12, 15, 17):
        scheduler.add_job(auto_remind_day_of_followup, trigger='cron', hour=hour, minute=0,
                          args=[bot, db, admin_ids, hour])
    scheduler.start()
    logger.info('APScheduler started')
    return scheduler
