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
from states import RegistrationState
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

    def update(self, text=None, callback=None, user=42, contact=None):
        self.sequence += 1
        message = dict(message_id=self.sequence, date=int(datetime.now(timezone.utc).timestamp()),
                       chat={'id': user, 'type': 'private'},
                       from_user={'id': user, 'is_bot': False, 'first_name': 'Private'}, text=text)
        if contact:
            message['contact'] = contact
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
        await self.feed(self.update(callback='register_event_50'))
        self.assertEqual(report(self.path)['registrations_started'], 0)
        self.assertIn('Вы уже зарегистрированы', self.session.calls[-2].text)
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)

    def context(self):
        return self.dp.fsm.get_context(bot=self.bot, chat_id=42, user_id=42)

    def use_integrated_database(self):
        from pathlib import Path
        from analytics import Analytics
        from sqlite_fixture import TestDatabase
        self.db = TestDatabase(str(Path(self.tmp.name) / 'integrated.db'))
        self.path = Path(self.db.db_path + '.analytics.sqlite')
        self.analytics = Analytics(self.path)
        with self.db._connect() as conn:
            conn.execute("INSERT INTO events(id,title,description,event_date,event_time,location,price_text,max_teams) VALUES(50,'Synthetic quiz','','2099-01-01','19:00','Test','Test',12)")
        self.db.upsert_user(42, None, 'Private profile', 'ru')

    async def test_integrated_contact_profile_resume_and_private_report_50(self):
        from states import SubscribeState
        self.use_integrated_database()
        await self.feed(self.update(text='/start event_50_src_instagram'))
        await self.feed(self.update(callback='fill_profile'))
        await self.feed(self.update(text='Private profile'))
        await self.feed(self.update(contact={'phone_number': '998901234567', 'first_name': 'Private', 'user_id': 99}))
        self.assertIsNone(self.db.get_subscriber_profile(42))
        self.assertEqual(await self.context().get_state(), SubscribeState.phone.state)
        await self.feed(self.update(contact={'phone_number': '998901234567', 'first_name': 'Private', 'user_id': 42}))
        self.assertEqual(self.db.get_subscriber_profile(42)['phone'], '+998901234567')
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(text='Private team'))
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(callback=self.button('reg_resume_')))
        for value in ('5', 'Private captain', '+998901234567', '-'):
            await self.feed(self.update(text=value))
        await asyncio.gather(self.feed(self.update(callback='confirm_registration')),
                             self.feed(self.update(callback='confirm_registration')))
        with self.db._connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)
        self.assertEqual(report(self.path, source='instagram')['registrations_completed'], 1)
        before = len(self.session.calls)
        await self.dp.feed_update(self.bot, self.update(text='/report 50'), db=self.db,
                                  admin_ids=[42], analytics=self.analytics)
        text = '\n'.join(getattr(call, 'text', '') or '' for call in self.session.calls[before:])
        for value in ('#50', '1/12 команд', '5 заявленных', '24ч: 1 / 1', 'instagram: 1 нач., 1 заверш.'):
            self.assertIn(value, text)
        for private in ('Private profile', 'Private team', 'Private captain', '+998901234567'):
            self.assertNotIn(private, text)

    async def test_integrated_existing_profile_and_manual_phone(self):
        from states import SubscribeState
        self.use_integrated_database()
        await self.feed(self.update(text='📬 Получать анонсы'))
        await self.feed(self.update(text='Private profile'))
        await self.feed(self.update(text='+998 (90) 123-45-67'))
        profile = dict(self.db.get_subscriber_profile(42))
        self.assertIsNone(await self.context().get_state())
        self.assertEqual(profile['phone'], '+998901234567')
        for update in (self.update(callback='fill_profile'), self.update(text='📬 Получать анонсы')):
            await self.feed(update)
            self.assertIsNone(await self.context().get_state())
            self.assertEqual(dict(self.db.get_subscriber_profile(42)), profile)
        await self.feed(self.update(text='/start event_50_src_qr'))
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(callback=self.button('reg_restart_')))
        await self.feed(self.update(text='/cancel'))
        out = report(self.path, event_id=50, source='qr')
        self.assertEqual(out['registrations_started'], 2)
        self.assertEqual(out['outcome_counts']['superseded'], 1)
        self.assertEqual(out['outcome_counts']['cancelled'], 1)

    def button(self, prefix):
        messages = [c for c in self.session.calls if getattr(c, 'reply_markup', None)
                    and hasattr(c.reply_markup, 'inline_keyboard')]
        return next(b.callback_data for row in messages[-1].reply_markup.inline_keyboard
                    for b in row if b.callback_data.startswith(prefix))

    async def test_resume_every_stage_without_new_start_or_step(self):
        await self.feed(self.update(text='/start event_50'))
        await self.feed(self.update(callback='register_event_50'))
        stages = [RegistrationState.team_name, RegistrationState.team_size,
                  RegistrationState.captain_name, RegistrationState.phone,
                  RegistrationState.comment, RegistrationState.confirm,
                  RegistrationState.choose_event]
        for stage in stages:
            with self.subTest(stage=stage.state):
                await self.context().set_state(stage)
                await self.context().update_data(team_name='Synthetic', team_size=5,
                    captain_name='Synthetic', phone='+998901234567', comment='')
                before = await self.context().get_data()
                count = len(self.rows())
                await self.feed(self.update(callback='register_event_50'))
                self.assertIn('Вы уже начали регистрацию', self.session.calls[-2].text)
                await self.feed(self.update(callback=self.button('reg_resume_')))
                self.assertEqual(await self.context().get_state(), stage.state)
                self.assertEqual(await self.context().get_data(), before)
                self.assertEqual(len(self.rows()), count)
        self.assertEqual(report(self.path)['registrations_started'], 1)

    async def test_restart_supersedes_and_stale_button_cannot_reset_again(self):
        await self.feed(self.update(text='/start event_50_src_instagram'))
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(text='Synthetic'))
        old = (await self.context().get_data())['attempt_id']
        await self.feed(self.update(callback='register_event_50'))
        restart = self.button('reg_restart_')
        await asyncio.gather(self.feed(self.update(callback=restart)),
                             self.feed(self.update(callback=restart)))
        new = await self.context().get_data()
        self.assertNotEqual(old, new['attempt_id'])
        self.assertNotIn('team_name', new)
        self.assertEqual(new['attempt_source'], 'instagram')
        await self.feed(self.update(callback=restart))
        self.assertEqual(await self.context().get_data(), new)
        out = report(self.path)
        self.assertEqual(out['registrations_started'], 2)
        self.assertEqual(out['outcome_counts']['superseded'], 1)
        self.assertEqual(out['outcome_counts']['unfinished'], 1)
        self.assertEqual(out['technical_error_events'], 0)
        self.assertEqual(out['steps'], {'team_name': 1})
        await self.feed(self.update(callback='reg_cancel'))
        self.assertEqual(report(self.path)['outcome_counts']['cancelled'], 1)

    async def test_incomplete_progress_only_offers_restart(self):
        await self.feed(self.update(callback='register_event_50'))
        await self.context().set_state(RegistrationState.confirm)
        await self.feed(self.update(callback='register_event_50'))
        self.assertIn('неполная', self.session.calls[-2].text)
        restart = self.button('reg_restart_')
        await self.feed(self.update(callback=restart))
        self.assertEqual(await self.context().get_state(), RegistrationState.team_name.state)
        self.assertEqual(report(self.path)['outcome_counts']['superseded'], 1)

    async def test_menu_choose_event_resumes_without_picking_or_resetting(self):
        await self.feed(self.update(text='📝 Регистрация'))
        await self.fill(start=False)
        self.assertEqual(await self.context().get_state(), RegistrationState.choose_event.state)
        before = await self.context().get_data()
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(callback=self.button('reg_resume_')))
        self.assertEqual(await self.context().get_data(), before)
        self.assertEqual(await self.context().get_state(), RegistrationState.choose_event.state)
        await self.feed(self.update(callback='reg_pick_event_50'))
        await self.feed(self.update(callback='confirm_registration'))
        self.assertEqual(report(self.path)['registrations_started'], 1)
        self.assertEqual(report(self.path)['registrations_completed'], 1)

    async def test_missing_attempt_id_and_unknown_state_offer_restart(self):
        for current in (RegistrationState.phone.state, 'RegistrationState:obsolete'):
            await self.context().clear()
            await self.context().set_state(current)
            await self.feed(self.update(callback='register_event_50'))
            restart = self.button('reg_restart_')
            self.assertEqual(report(self.path)['technical_error_events'], 0)
            await self.feed(self.update(callback=restart))
            self.assertEqual(await self.context().get_state(), RegistrationState.team_name.state)

    async def test_storage_loss_offers_safe_restart_and_leaves_old_unfinished(self):
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(text='Synthetic'))
        await self.feed(self.update(callback='register_event_50'))
        resume = self.button('reg_resume_')
        self.dp.fsm.storage = MemoryStorage()
        await self.feed(self.update(callback=resume))
        restart = self.button('reg_restart_')
        await self.feed(self.update(callback=restart))
        self.assertEqual(await self.context().get_state(), RegistrationState.team_name.state)
        out = report(self.path)
        self.assertEqual(out['registrations_started'], 2)
        self.assertEqual(out['outcome_counts']['unfinished'], 2)
        self.assertEqual(out['technical_error_events'], 0)

    async def test_closed_game_blocks_resume_restart_and_confirmation(self):
        await self.fill()
        await self.feed(self.update(callback='register_event_50'))
        resume, restart = self.button('reg_resume_'), self.button('reg_restart_')
        for status in ('closed', 'cancelled'):
            self.db.get_event_by_id = lambda game: {**self.event, 'status': status}
            for callback in ('register_event_50', resume, restart, 'confirm_registration'):
                await self.feed(self.update(callback=callback))
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 0)
        self.assertEqual(report(self.path)['registrations_started'], 1)

    async def test_resume_can_complete_booking_and_duplicate_click_does_not_start(self):
        await self.feed(self.update(text='/start event_50'))
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(text='Synthetic'))
        await self.feed(self.update(callback='register_event_50'))
        await self.feed(self.update(callback=self.button('reg_resume_')))
        for text in ('5', 'Synthetic', '+998901234567', '-'):
            await self.feed(self.update(text=text))
        await self.feed(self.update(callback='confirm_registration'))
        await self.feed(self.update(callback='register_event_50'))
        self.assertIn('Вы уже зарегистрированы', self.session.calls[-2].text)
        out = report(self.path)
        self.assertEqual(out['registrations_started'], 1)
        self.assertEqual(out['registrations_completed'], 1)

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
