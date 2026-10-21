import asyncio
from contextlib import ExitStack
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import app
import scheduling


class SchedulerFlagTests(unittest.TestCase):
    def test_default_enabled_and_explicit_values(self):
        for value, expected in ((None, True), ('1', True), ('0', False), (' 0 ', False)):
            with self.subTest(value=value), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ['SCHEDULER_ENABLED'] = value
                self.assertEqual(scheduling.scheduler_enabled(), expected)

    def test_invalid_value_rejected(self):
        for value in ('', 'false', 'true', '2'):
            with self.subTest(value=value), patch.dict(os.environ, {'SCHEDULER_ENABLED': value}, clear=True):
                with self.assertRaisesRegex(ValueError, 'SCHEDULER_ENABLED must be 0 or 1'):
                    scheduling.scheduler_enabled()

    def test_disabled_does_not_construct_scheduler(self):
        with patch('scheduling.AsyncIOScheduler') as constructor:
            self.assertIsNone(scheduling.start_scheduler(None, None, [], 0, enabled=False))
            constructor.assert_not_called()

    def test_enabled_preserves_all_jobs_and_arguments(self):
        bot, db, admins, channel = object(), object(), [42], -1
        with patch('scheduling.AsyncIOScheduler') as constructor:
            scheduler = scheduling.start_scheduler(bot, db, admins, channel)
            constructor.assert_called_once_with(timezone='Asia/Tashkent')
            self.assertIs(scheduler, constructor.return_value)
            scheduler.start.assert_called_once_with()
            self.assertEqual(scheduler.add_job.call_count, 7)
            jobs = scheduler.add_job.call_args_list
            self.assertEqual(jobs[0].args, (scheduling.check_giveaway_schedule,))
            self.assertEqual(jobs[0].kwargs, dict(trigger='cron', minute='*', args=[bot,db,admins,channel]))
            self.assertEqual(jobs[1].args, (scheduling.send_friday_winner_reminders,))
            self.assertEqual(jobs[1].kwargs, dict(trigger='cron', day_of_week='thu', hour=21, minute=10,
                                                  args=[bot,db,admins]))
            for index, func in ((2,scheduling.auto_remind_day_before),(3,scheduling.auto_remind_day_of)):
                self.assertEqual(jobs[index].args, (func,))
                self.assertEqual(jobs[index].kwargs, dict(trigger='cron', hour=10, minute=0, args=[bot,db,admins]))
            for job, hour in zip(jobs[4:], (12,15,17)):
                self.assertEqual(job.args, (scheduling.auto_remind_day_of_followup,))
                self.assertEqual(job.kwargs, dict(trigger='cron',hour=hour,minute=0,args=[bot,db,admins,hour]))


class SchedulerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_digest_schedule_and_restart_have_exactly_one_daily_job(self):
        with patch.dict(os.environ, {'ADMIN_DIGEST_ENABLED': '1'}):
            for _ in range(2):
                scheduler = scheduling.start_scheduler(object(), object(), [], 0)
                try:
                    jobs = scheduler.get_jobs()
                    self.assertEqual(len(jobs), 8)
                    daily = [j for j in jobs if j.id == 'admin_daily_digest']
                    self.assertEqual(len(daily), 1)
                    self.assertEqual(daily[0].next_run_time.hour, 9)
                    self.assertEqual(daily[0].next_run_time.minute, 0)
                    self.assertEqual(str(daily[0].next_run_time.tzinfo), 'Asia/Tashkent')
                finally:
                    scheduler.shutdown()
                    await asyncio.sleep(0)

    async def run_application(self, value, *, error=None, already_stopped=False):
        # All startup I/O is replaced: no config/.env, business DB or Telegram.
        config = SimpleNamespace(bot_token='offline', db_path='unused-test.db', admin_ids=[], channel_id=0)
        db = object()
        bot = SimpleNamespace(send_message=AsyncMock())
        dp = SimpleNamespace(start_polling=AsyncMock(side_effect=error))
        analytics = object()
        environment = {'FUNNEL_ANALYTICS_ENABLED': '1'}
        if value is not None:
            environment['SCHEDULER_ENABLED'] = value
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, environment, clear=True))
            stack.enter_context(patch.dict(sys.modules, {'config': SimpleNamespace(load_config=lambda: config)}))
            database = stack.enter_context(patch('app.Database', return_value=db))
            stack.enter_context(patch('app.sync_templates_to_db'))
            stack.enter_context(patch('app.Bot', return_value=bot))
            journal = stack.enter_context(patch('app.Analytics', return_value=analytics))
            dispatcher = stack.enter_context(patch('app.create_dispatcher', return_value=dp))
            constructor = stack.enter_context(patch('scheduling.AsyncIOScheduler'))
            stack.enter_context(patch('builtins.print'))
            constructor.return_value.running = not already_stopped
            if value == 'bad':
                with self.assertRaises(ValueError):
                    await app.main()
                database.assert_not_called()
                return
            if error is not None:
                with self.assertRaises(type(error)):
                    await app.main()
            else:
                await app.main()
            journal.assert_called_once_with('unused-test.db.analytics.sqlite')
            dispatcher.assert_called_once_with(db, bot, [], analytics)
            dp.start_polling.assert_awaited_once_with(bot)
            if value == '0':
                constructor.assert_not_called()
            else:
                constructor.return_value.start.assert_called_once_with()
                if already_stopped:
                    constructor.return_value.shutdown.assert_not_called()
                else:
                    constructor.return_value.shutdown.assert_called_once_with()

    async def test_both_modes_and_default_reach_polling_and_analytics(self):
        for value in ('0', '1', None):
            with self.subTest(value=value):
                await self.run_application(value)

    async def test_polling_error_shutdown_in_both_modes(self):
        for value in ('0', '1'):
            with self.subTest(value=value):
                await self.run_application(value, error=RuntimeError('test error'))

    async def test_cancellation_shutdown_in_both_modes(self):
        for value in ('0', '1'):
            with self.subTest(value=value):
                await self.run_application(value, error=asyncio.CancelledError())

    async def test_already_stopped_scheduler(self):
        await self.run_application('1', already_stopped=True)

    async def test_invalid_flag_fails_before_database(self):
        await self.run_application('bad')

    async def test_actual_apscheduler_start_shutdown_with_mock_jobs(self):
        # Exercise APScheduler itself on the interpreter under test. Never run real jobs.
        names = ('check_giveaway_schedule','send_friday_winner_reminders',
                 'auto_remind_day_before','auto_remind_day_of','auto_remind_day_of_followup')
        with patch.multiple(scheduling, **{name: AsyncMock() for name in names}):
            scheduler = scheduling.start_scheduler(object(), object(), [], 0)
            try:
                self.assertTrue(scheduler.running)
                self.assertEqual(len(scheduler.get_jobs()), 7)
                self.assertEqual(str(scheduler.timezone), 'Asia/Tashkent')
            finally:
                scheduler.shutdown()
                await asyncio.sleep(0)
            self.assertFalse(scheduler.running)


if __name__ == '__main__':
    unittest.main()
