"""Feed actual Telegram Update models through production routing, without HTTP."""
import asyncio
from datetime import datetime, timezone
import unittest
import os
from unittest.mock import patch

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import Message, Update, User

from analytics import report
from app import create_dispatcher
from scheduling import scheduler_enabled, start_scheduler
import test_analytics as fixtures


class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ == 'getMe':
            return User(id=1, is_bot=True, first_name='Offline', username='OfflineTestBot')
        if method.__api_method__ == 'answerCallbackQuery':
            return True
        if method.__api_method__ in {'sendMessage', 'sendPhoto'}:
            return Message(message_id=10000+len(self.calls), date=datetime.now(timezone.utc),
                           chat={'id': method.chat_id, 'type': 'private'},
                           text=getattr(method, 'text', None))
        raise AssertionError('Unexpected API method: offline tests allow no polling or HTTP')

    async def stream_content(self, *args, **kwargs):
        raise AssertionError('Network access forbidden')
        yield b''


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    create_registration = fixtures.FunnelTests.create_registration
    rows = fixtures.FunnelTests.rows

    @classmethod
    def setUpClass(cls):
        # Original routers are attached exactly once, in the actual app order.
        cls.dp = create_dispatcher(None, None, [])

    async def asyncSetUp(self):
        await fixtures.FunnelTests.asyncSetUp(self)
        self.session = OfflineSession()
        # Synthetic local credential; the session has no HTTP implementation.
        self.bot = Bot(token=str(1) + ':' + 'offline_placeholder'.ljust(35, 'x'), session=self.session)
        self.addAsyncCleanup(self.bot.session.close)
        self.dp.fsm.storage = MemoryStorage()
        self.dp.fsm.events_isolation = SimpleEventIsolation()
        self.addAsyncCleanup(self.dp.fsm.events_isolation.close)
        self.db.blitz_get_session = lambda: None
        self.db.get_event_by_id = lambda game: {**self.event, 'id': game}

    def update(self, text=None, callback=None, user=42):
        self.sequence += 1
        message = dict(message_id=self.sequence, date=int(datetime.now(timezone.utc).timestamp()),
                       chat={'id': user, 'type': 'private'},
                       from_user={'id': user, 'is_bot': False, 'first_name': 'Private'}, text=text)
        if text and text.startswith('/'):
            message['entities'] = [{'type': 'bot_command', 'offset': 0, 'length': len(text.split()[0])}]
        if callback:
            return Update(update_id=self.sequence, callback_query={
                'id': str(self.sequence), 'chat_instance': 'offline', 'from_user': message['from_user'],
                'message': message, 'data': callback})
        return Update(update_id=self.sequence, message=message)

    async def feed(self, update):
        return await self.dp.feed_update(self.bot, update, db=self.db, admin_ids=[], analytics=self.analytics)

    async def test_reports_access_arguments_button_and_active_fsm(self):
        from states import RegistrationState
        self.db.db_path = self.business.execute('PRAGMA database_list').fetchone()[2]
        self.business.execute("ALTER TABLE registrations ADD COLUMN status TEXT DEFAULT 'confirmed'")
        self.business.execute('ALTER TABLE registrations ADD COLUMN team_size INTEGER DEFAULT 5')
        self.business.execute('CREATE TABLE events(id INTEGER, title TEXT, event_date TEXT, event_time TEXT, max_teams INTEGER, status TEXT)')
        self.business.execute("INSERT INTO events VALUES(50,'Test game','2099-01-01','19:00',12,'open')")
        self.business.commit()
        state = self.dp.fsm.get_context(bot=self.bot, chat_id=42, user_id=42)
        await state.set_state(RegistrationState.team_name)
        await state.set_data({'attempt_id': 'keep-this', 'event_id': 50})
        for text in ('/report', '/report@OfflineTestBot 50', '📈 Отчёт по играм'):
            before = len(self.session.calls)
            await self.dp.feed_update(self.bot, self.update(text=text), db=self.db, admin_ids=[42])
            sent = self.session.calls[before:]
            self.assertTrue(any('#50' in (getattr(m, 'text', '') or '') for m in sent))
            self.assertEqual(await state.get_state(), RegistrationState.team_name.state)
            self.assertEqual(await state.get_data(), {'attempt_id': 'keep-this', 'event_id': 50})
        for text in ('/report 0', '/report nope', '/report 50 51', '/report ' + '9' * 100):
            await self.dp.feed_update(self.bot, self.update(text=text), db=self.db, admin_ids=[42])
            self.assertIn('Использование', self.session.calls[-1].text)
        for text in ('/report', '/report 50', '📈 Отчёт по играм'):
            await self.feed(self.update(text=text))
            self.assertIn('нет доступа', self.session.calls[-1].text)
            self.assertEqual(await state.get_state(), RegistrationState.team_name.state)

    async def fill(self, start=True):
        if start:
            await self.feed(self.update(callback='register_event_50'))
        for text in ('Private team', '5', 'Private captain', '+998901234567', '-'):
            await self.feed(self.update(text=text))

    async def test_real_filters_middleware_source_and_concurrent_confirmation(self):
        await self.feed(self.update(text='/start event_50_src_instagram'))
        await asyncio.gather(self.feed(self.update(callback='register_event_50')),
                             self.feed(self.update(callback='register_event_50')))
        await self.fill(start=False)
        await asyncio.gather(self.feed(self.update(callback='confirm_registration')),
                             self.feed(self.update(callback='confirm_registration')))
        result = report(self.path, event_id=50, source='instagram')
        self.assertEqual(result['bot_starts'], 1)
        self.assertEqual(result['registrations_started'], 1)
        self.assertEqual(result['registrations_completed'], 1)
        self.assertEqual(result['steps'], dict(captain_name=1, comment=1, phone=1, team_name=1, team_size=1))
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)

    async def test_dispatcher_all_cancellations_and_legacy_link(self):
        await self.feed(self.update(text='/start event_50'))
        for value in ('reg_cancel', 'cancel_registration', '/cancel'):
            await self.feed(self.update(callback='register_event_50'))
            await self.feed(self.update(text=value) if value.startswith('/') else self.update(callback=value))
        out = report(self.path, event_id=50)
        self.assertEqual(out['outcome_counts']['cancelled'], 3)
        self.assertEqual(out['unfinished'], [])
        self.assertEqual(out['event_cards_sent'], 1)

    async def test_dispatcher_restart_and_late_menu_game_selection(self):
        await self.feed(self.update(text='📝 Регистрация'))
        await self.feed(self.update(text='Team'))
        self.dp.fsm.storage = MemoryStorage()
        await self.feed(self.update(callback='confirm_registration'))
        self.assertEqual(report(self.path)['outcome_counts']['unfinished'], 1)
        self.assertEqual(len(report(self.path)['unlinked_failures']), 1)
        await self.feed(self.update(text='📝 Регистрация'))
        await self.fill(start=False)
        await self.feed(self.update(callback='reg_pick_event_50'))
        await self.feed(self.update(callback='confirm_registration'))
        out = report(self.path, event_id=50)
        self.assertEqual(out['registrations_started'], 1)
        self.assertEqual(out['registrations_completed'], 1)
        self.assertEqual(out['completed'][0]['source'], 'menu')

    async def test_dispatcher_failure_classification_and_recovery(self):
        await self.fill()
        original = self.db.create_registration
        def fail(**kw):
            raise RuntimeError('private-exception')
        self.db.create_registration = fail
        with self.assertRaises(RuntimeError):
            await self.feed(self.update(callback='confirm_registration'))
        self.assertEqual(report(self.path)['outcome_counts']['technical_errors'], 1)
        self.db.create_registration = original
        await self.feed(self.update(callback='confirm_registration'))
        out = report(self.path)
        self.assertEqual(out['outcome_counts']['technical_errors'], 0)
        self.assertEqual(out['technical_error_events'], 1)
        self.assertEqual(out['registrations_completed'], 1)

    async def test_dispatcher_analytics_failure_and_duplicate_booking(self):
        self.analytics.path = str(self.path.parent / 'missing' / 'journal.sqlite')
        await self.fill()
        await self.feed(self.update(callback='confirm_registration'))
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)
        self.analytics.path = str(self.path)
        await self.fill()
        await self.feed(self.update(callback='confirm_registration'))
        self.assertEqual(report(self.path)['outcome_counts']['duplicates'], 1)

    async def test_other_game_does_not_inherit_source_and_invalid_input_not_completed(self):
        await self.feed(self.update(text='/start event_51_src_qr'))
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(text='Team'))
        await self.feed(self.update(text='not a number'))
        out = report(self.path, event_id=50)
        self.assertEqual(out['steps'], {'team_name': 1})
        self.assertEqual(out['unfinished'][0]['source'], 'direct')

    async def test_source_survives_edit_without_relabeling_active_attempt(self):
        await self.feed(self.update(text='/start event_50_src_instagram'))
        await self.fill()
        await self.feed(self.update(text='/start event_50_src_qr'))
        await self.feed(self.update(callback='edit_registration'))
        await self.fill(start=False)
        await self.feed(self.update(callback='confirm_registration'))
        self.assertEqual(report(self.path, source='instagram')['registrations_completed'], 1)
        self.assertEqual(report(self.path, source='qr')['registrations_completed'], 0)

    async def test_unknown_source_is_not_stored_as_raw_payload(self):
        await self.feed(self.update(text='/start event_50_src_private-name'))
        await self.fill()
        await self.feed(self.update(callback='confirm_registration'))
        self.assertEqual(report(self.path, source='unknown')['registrations_completed'], 1)
        self.assertNotIn('private-name', str(self.rows()))

    async def test_scheduler_modes_do_not_change_registration_and_analytics(self):
        for count, value in enumerate(('0', '1'), start=1):
            with self.subTest(value=value), patch.dict(os.environ, {'SCHEDULER_ENABLED': value}), \
                    patch('scheduling.AsyncIOScheduler') as constructor:
                scheduler = start_scheduler(self.bot, self.db, [], 0, enabled=scheduler_enabled())
                await self.fill()
                await self.feed(self.update(callback='confirm_registration'))
                self.assertEqual(report(self.path)['registrations_completed'], count)
                self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)
                if value == '0':
                    constructor.assert_not_called()
                    self.assertIsNone(scheduler)
                else:
                    scheduler.start.assert_called_once_with()
                    scheduler.shutdown()
                # Independent booking fixture for the next mode, not a live database.
                self.business.execute('DELETE FROM registrations')
                self.business.commit()


if __name__ == '__main__':
    unittest.main()
