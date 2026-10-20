import asyncio
import gc
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.exceptions import (TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter,
                               TelegramBadRequest, TelegramServerError)
from aiogram.types import Update, Message

from database import Database
from delivery import (configure_delivery, DeliverySkipped, tracked_broadcast,
                      delivery_recipients, set_campaign_unit, classify_error)
from handlers import common, admin, giveaway
import test_dispatcher as offline


class TestDatabase(Database):
    def _restore_backup_if_empty(self):
        pass  # Never insert historical backup data in tests.


class ScriptedSession(offline.OfflineSession):
    def __init__(self):
        super().__init__()
        self.outcomes = {}
        self.before_error = None

    async def make_request(self, bot, method, timeout=None):
        queue = self.outcomes.get(getattr(method,'chat_id',None), [])
        outcome = queue.pop(0) if queue else None
        if outcome:
            self.calls.append(method)
            if self.before_error:
                self.before_error()
            errors = {
                'blocked': lambda: TelegramForbiddenError(method,'Forbidden: bot was blocked by the user'),
                'forbidden_other': lambda: TelegramForbiddenError(method,'Forbidden: not enough rights'),
                'deactivated': lambda: TelegramForbiddenError(method,'Forbidden: user is deactivated'),
                'network': lambda: TelegramNetworkError(method,'temporary network failure'),
                'rate_limited': lambda: TelegramRetryAfter(method,'retry later',retry_after=1),
                'bad_request': lambda: TelegramBadRequest(method,'invalid message'),
                'server_error': lambda: TelegramServerError(method,'temporary server failure'),
            }
            raise errors[outcome]()
        return await super().make_request(bot,method,timeout)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'test.sqlite'
        self.db = TestDatabase(str(self.path))
        self.addCleanup(gc.collect)
        self.uid = 900000101
        self.db.upsert_user(self.uid,None,'Synthetic','ru')
        self.session = ScriptedSession()
        self.bot = Bot(token='1:'+'offline_placeholder'.ljust(35,'x'),session=self.session)
        self.addAsyncCleanup(self.bot.session.close)
        configure_delivery(self.bot,self.db)

    async def send(self):
        return await self.bot.send_message(self.uid,'Synthetic')

    async def test_confirmed_block_persists_and_skips_all_private_send_methods(self):
        self.session.outcomes[self.uid] = ['blocked']
        with self.assertRaises(TelegramForbiddenError):
            await self.send()
        self.assertEqual(self.db.get_delivery_state(self.uid)['availability'],'blocked')
        self.assertEqual(self.db.get_subscribers(),[])
        self.assertEqual(self.db.get_giveaway_non_participants(1),[])
        self.db = TestDatabase(str(self.path))
        # Reconfigure a new bot after restart: the database, not memory, excludes the contact.
        second = Bot(token='1:'+'offline_placeholder'.ljust(35,'x'),session=ScriptedSession())
        self.addAsyncCleanup(second.session.close)
        configure_delivery(second,self.db)
        for call in (lambda: second.send_message(self.uid,'Synthetic'),
                     lambda: second.send_photo(self.uid,'offline-photo'),
                     lambda: second.send_document(self.uid,'offline-file')):
            with self.assertRaises(DeliverySkipped):
                await call()
        self.assertEqual(second.session.calls,[])

    async def test_non_block_errors_remain_retryable(self):
        for category in ('network','rate_limited','forbidden_other','deactivated','bad_request','server_error'):
            with self.subTest(category=category):
                self.session.outcomes[self.uid] = [category]
                try:
                    await self.send()
                except Exception as error:
                    self.assertEqual(classify_error(error),category)
                else:
                    self.fail('Expected failure')
                self.assertNotEqual(self.db.get_delivery_state(self.uid)['availability'],'blocked')
                self.assertEqual(len(self.db.get_subscribers()),1)
                await self.send()
        state = self.db.get_delivery_state(self.uid)
        self.assertEqual(state['availability'],'reachable')
        self.assertTrue(state['last_successful_send_at'].endswith('Z'))

    async def test_subscription_and_last_success_survive_reinitialization(self):
        await self.send()
        timestamp = self.db.get_delivery_state(self.uid)['last_successful_send_at']
        self.db.set_subscription(self.uid,False)
        self.db.mark_delivery_blocked(self.uid)
        restarted = TestDatabase(str(self.path))
        self.assertEqual(restarted.get_user_by_telegram_id(self.uid)['subscribed'],0)
        self.assertEqual(restarted.get_delivery_state(self.uid)['availability'],'blocked')
        self.assertEqual(restarted.get_delivery_state(self.uid)['last_successful_send_at'],timestamp)
        self.assertEqual(restarted.get_delivery_report()['api_results']['success'],1)
        restarted.set_subscription(self.uid,True)
        self.assertEqual(restarted.get_subscribers(),[])  # Subscription is not reachability.
        restarted.restore_availability(self.uid)
        self.assertEqual(len(restarted.get_subscribers()),1)

    async def test_start_and_unblock_events_do_not_resubscribe(self):
        self.db.set_subscription(self.uid,False)
        self.db.mark_delivery_blocked(self.uid)
        router = Router()
        router.message.register(common.cmd_start,Command('start'))
        router.message.register(common.subscribe_start,Command('subscribe'))
        router.my_chat_member.register(common.private_chat_availability)
        dp = Dispatcher(db=self.db,admin_ids=[],analytics=None)
        dp.include_router(router)
        self.db.get_open_events = lambda: []
        self.db.get_subscriber_profile = lambda _: True
        await dp.feed_update(self.bot,Update(update_id=0,message=dict(
            message_id=1,date=1,chat={'id':-100,'type':'group'},
            from_user={'id':self.uid,'is_bot':False,'first_name':'Synthetic'},text='/start')))
        self.assertEqual(self.db.get_delivery_state(self.uid)['availability'],'blocked')
        await dp.feed_update(self.bot,Update(update_id=1,message=dict(
            message_id=1,date=1,chat={'id':self.uid,'type':'private'},
            from_user={'id':self.uid,'is_bot':False,'first_name':'Synthetic'},text='/start')))
        self.assertEqual(self.db.get_user_by_telegram_id(self.uid)['subscribed'],0)
        self.assertEqual(self.db.get_delivery_state(self.uid)['availability'],'reachable')
        def member_update(index,status,chat_type='private'):
            return Update(update_id=index,my_chat_member=dict(chat={'id':self.uid,'type':chat_type},date=1,
                from_user={'id':self.uid,'is_bot':False,'first_name':'Synthetic'},
                old_chat_member={'user':{'id':1,'is_bot':True,'first_name':'Offline'},'status':'member'},
                new_chat_member={'user':{'id':1,'is_bot':True,'first_name':'Offline'},'status':status,
                                 **({'until_date':0} if status=='kicked' else {})}))
        await dp.feed_update(self.bot,member_update(2,'kicked'))
        self.assertEqual(self.db.get_delivery_state(self.uid)['availability'],'blocked')
        await dp.feed_update(self.bot,member_update(3,'member'))
        self.assertEqual(self.db.get_user_by_telegram_id(self.uid)['subscribed'],0)
        await dp.feed_update(self.bot,Update(update_id=4,message=dict(message_id=4,date=1,
            chat={'id':self.uid,'type':'private'},from_user={'id':self.uid,'is_bot':False,'first_name':'Synthetic'},text='/subscribe')))
        self.assertEqual(self.db.get_user_by_telegram_id(self.uid)['subscribed'],1)
        await dp.feed_update(self.bot,member_update(5,'kicked','group'))
        self.assertEqual(self.db.get_delivery_state(self.uid)['availability'],'reachable')

    async def test_late_block_response_cannot_undo_new_start(self):
        self.session.outcomes[self.uid] = ['blocked']
        self.session.before_error = lambda: self.db.restore_availability(self.uid)
        with self.assertRaises(TelegramForbiddenError):
            await self.send()
        self.assertEqual(self.db.get_delivery_state(self.uid)['availability'],'reachable')

    async def test_supplemental_failure_does_not_fail_main_or_publish_ids(self):
        self.session.outcomes[self.uid] = [None,'blocked']
        event = dict(id=1,photo_file_id=None)
        message = SimpleNamespace(from_user=SimpleNamespace(id=42),answer=AsyncMock())
        self.db.has_active_registration_by_telegram = lambda *args: True
        await admin._do_broadcast(message,self.db,self.bot,event,'Synthetic')
        report = self.db.get_delivery_report()
        run = report['recent_runs'][0]
        self.assertEqual(run['primary_success'],1)
        self.assertEqual(run['primary_errors'],{})
        self.assertEqual(run['additional'],dict(attempts=1,success=0,errors={'blocked':1}))
        self.assertEqual(run['attempts'],1)
        self.assertNotIn(str(self.uid),message.answer.call_args.args[0])
        self.assertNotIn(str(self.uid),json.dumps(report))

    async def test_multipart_main_is_not_success_when_text_after_photo_fails(self):
        self.session.outcomes[self.uid] = [None,'network']
        self.db.has_active_registration_by_telegram = lambda *args: False
        message = SimpleNamespace(from_user=SimpleNamespace(id=42),answer=AsyncMock())
        await admin._do_broadcast(message,self.db,self.bot,dict(id=1,photo_file_id='offline-photo'),'x'*1100)
        run = self.db.get_delivery_report()['recent_runs'][0]
        self.assertEqual(run['primary_success'],0)
        self.assertEqual(run['primary_errors'],{'network':1})
        self.assertEqual(run['attempts'],1)

    async def test_custom_batch_skips_winner_not_in_users_and_records_other_contact(self):
        other = self.uid+1
        self.db.mark_delivery_blocked(other)
        @tracked_broadcast
        async def winners(bot,db,admin_ids):
            rows = [{'telegram_id':uid} for uid in (self.uid,other,0,None)]
            for row in delivery_recipients(rows,db):
                try:
                    await bot.send_message(row['telegram_id'],'Synthetic')
                except Exception:
                    pass
        await winners(self.bot,self.db,[])
        run = self.db.get_delivery_report()['recent_runs'][0]
        self.assertEqual(run['skipped_blocked'],1)
        self.assertEqual(run['attempts'],1)
        self.assertEqual(run['invalid_recipients'],2)
        self.assertEqual(self.db.get_delivery_report()['other_private_contacts'],1)

    async def test_report_is_admin_only_and_aggregate_only(self):
        callback = SimpleNamespace(from_user=SimpleNamespace(id=42),answer=AsyncMock(),
                                   message=SimpleNamespace(answer=AsyncMock()))
        await self.send()
        await admin.delivery_report(callback,self.db,[42])
        self.assertNotIn(str(self.uid),callback.message.answer.call_args.args[0])
        callback.message.answer.reset_mock()
        await admin.delivery_report(callback,self.db,[])
        callback.message.answer.assert_not_awaited()

    async def test_tracking_database_failure_does_not_break_send(self):
        self.db.get_delivery_state = Mock(side_effect=RuntimeError('do not expose'))
        self.db.mark_delivery_success = Mock(side_effect=RuntimeError('do not expose'))
        self.db.count_delivery_result = Mock(side_effect=RuntimeError('do not expose'))
        await self.send()

    async def test_channels_are_not_marked_as_blocked_users(self):
        self.session.outcomes[-100] = ['blocked']
        with self.assertRaises(TelegramForbiddenError):
            await self.bot.send_message(-100,'Synthetic')
        self.assertEqual(self.db.get_delivery_state(-100)['availability'],'unknown')

    async def test_giveaway_and_captain_mass_paths_use_same_state(self):
        self.db.save_giveaway_settings('Synthetic','Synthetic',None,'19:30','21:00',active=1)
        self.session.outcomes[self.uid] = ['blocked']
        await giveaway.giveaway_announce(self.bot,self.db,[])
        self.assertEqual(self.db.get_delivery_report()['recent_runs'][0]['primary_errors'],{'blocked':1})
        calls = len(self.session.calls)
        await giveaway.giveaway_reminder(self.bot,self.db,[])
        self.assertEqual(len(self.session.calls),calls)
        self.db.get_events_by_date = lambda _: [dict(id=1,title='Synthetic',location='Offline',location_url=None,event_time='18:00')]
        self.db.get_registrations_for_event = lambda _: [dict(id=1,telegram_id=self.uid,team_size=3)]
        await admin.auto_remind_day_of(self.bot,self.db,[])
        run = self.db.get_delivery_report()['recent_runs'][0]
        self.assertEqual(run['attempts'],0)
        self.assertEqual(run['skipped_blocked'],1)
        self.assertEqual(len(self.session.calls),calls)

    async def test_eligible_and_attempted_differ_on_interrupted_batch(self):
        other = self.uid+1
        @tracked_broadcast
        async def interrupted(bot,db,admin_ids):
            rows = delivery_recipients([{'telegram_id':self.uid},{'telegram_id':other}],db)
            await bot.send_message(rows[0]['telegram_id'],'Synthetic')
            raise RuntimeError('stop before second recipient')
        with self.assertRaises(RuntimeError):
            await interrupted(self.bot,self.db,[])
        run = self.db.get_delivery_report()['recent_runs'][0]
        self.assertEqual((run['eligible'],run['attempts'],run['primary_success']),(2,1,1))

    async def test_multiple_games_and_concurrent_runs_are_separate(self):
        @tracked_broadcast
        async def games(bot,db,admin_ids):
            for game in (1,2):
                set_campaign_unit(game)
                for row in delivery_recipients([{'telegram_id':self.uid}],db):
                    await bot.send_message(row['telegram_id'],'Synthetic')
        await asyncio.gather(games(self.bot,self.db,[]),games(self.bot,self.db,[]))
        for run in self.db.get_delivery_report()['recent_runs'][:2]:
            self.assertEqual((run['eligible'],run['attempts'],run['primary_success']),(2,2,2))

    async def test_only_forbidden_block_phrase_is_permanent(self):
        from aiogram.methods import SendMessage
        method = SendMessage(chat_id=self.uid,text='Synthetic')
        error = TelegramBadRequest(method,'bot was blocked by the user')
        self.assertEqual(classify_error(error),'bad_request')
        self.db.mark_delivery_blocked(self.uid)
        self.db.mark_delivery_success(self.uid)
        self.assertEqual(self.db.get_delivery_state(self.uid)['availability'],'blocked')

    async def test_connections_commit_rollback_and_close(self):
        with self.db._connect() as conn:
            conn.execute('UPDATE users SET subscribed=0')
        with self.assertRaises(Exception):
            conn.execute('SELECT 1')
        try:
            with self.db._connect() as conn:
                conn.execute('UPDATE users SET subscribed=1')
                raise RuntimeError('rollback')
        except RuntimeError:
            pass
        self.assertEqual(self.db.get_user_by_telegram_id(self.uid)['subscribed'],0)

    async def test_admin_callback_message_summary_not_counted_as_recipient(self):
        message = Message.model_validate(dict(message_id=1,date=1,chat={'id':42,'type':'private'},
            from_user={'id':1,'is_bot':True,'first_name':'Offline'}),context={'bot':self.bot})
        self.db.has_active_registration_by_telegram = lambda *args: False
        await admin._do_broadcast(message,self.db,self.bot,dict(id=1,photo_file_id=None),'Synthetic')
        report = self.db.get_delivery_report()
        self.assertEqual(report['recent_runs'][0]['eligible'],1)
        self.assertEqual(report['recent_runs'][0]['attempts'],1)
        self.assertEqual(report['api_attempts'],2)  # Recipient + admin summary are separate API calls.


if __name__ == '__main__':
    unittest.main()
