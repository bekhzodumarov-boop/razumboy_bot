import asyncio
import inspect
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from analytics import Analytics, report
from analytics_middleware import FunnelMiddleware
from handlers import registration as reg
from handlers import common
from states import RegistrationState


class FunnelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'journal.sqlite'
        self.analytics = Analytics(self.path)
        self.storage = MemoryStorage()
        self.state = FSMContext(self.storage, StorageKey(bot_id=1, chat_id=42, user_id=42))
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.event = dict(id=50, status='open', title='Test', event_date='2099-01-01',
                          event_time='18:00', description='', location='Test',
                          location_url=None, price_text='', photo_file_id=None)
        # Dedicated test business database; no production Database initializer.
        self.business = sqlite3.connect(Path(self.tmp.name) / 'business.sqlite')
        self.addCleanup(self.business.close)
        self.business.execute('CREATE TABLE registrations (event_id INTEGER, user_id INTEGER)')
        self.db = SimpleNamespace(
            get_event_by_id=lambda _: self.event,
            get_open_events=lambda: [self.event],
            get_last_registration_by_telegram=lambda _: None,
            get_user_by_telegram_id=lambda _: {'id': 42},
            has_active_registration=lambda e, u: bool(self.business.execute(
                'SELECT 1 FROM registrations WHERE event_id=? AND user_id=?', (e, u)).fetchone()),
            create_registration=self.create_registration,
            upsert_user=lambda **kw: None, set_subscription=lambda *args: None,
            get_subscriber_profile=lambda _: True)
        self.sequence = 0

    def create_registration(self, **kw):
        self.business.execute('INSERT INTO registrations VALUES (?,?)', (kw['event_id'], kw['user_id']))
        self.business.commit()
        return 1

    def message(self, text=None):
        self.sequence += 1
        return SimpleNamespace(text=text, chat=SimpleNamespace(id=42), message_id=self.sequence,
                               from_user=SimpleNamespace(id=42, username=None, full_name='private-name', language_code='ru'),
                               answer=AsyncMock(), answer_photo=AsyncMock())

    def callback(self, value):
        message = self.message()
        return SimpleNamespace(data=value, id=f'callback-{self.sequence}',
                               from_user=message.from_user, message=message, answer=AsyncMock())

    async def call(self, fn, event):
        data = dict(state=self.state, db=self.db, analytics=self.analytics, bot=self.bot, admin_ids=[])
        async def invoke(e, values):
            return await fn(e, **{k: v for k, v in values.items() if k in inspect.signature(fn).parameters})
        return await FunnelMiddleware()(invoke, event, data)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute('SELECT * FROM funnel_events ORDER BY id')]

    async def fill(self):
        await self.call(reg.register_from_event, self.callback('register_event_50'))
        await self.call(reg.reg_team_name, self.message('private-team'))
        await self.call(reg.reg_team_size, self.message('5'))
        await self.call(reg.reg_captain_name, self.message('private-name'))
        await self.call(reg.reg_phone, self.message('+998901234567'))
        await self.call(reg.reg_comment, self.message('private-comment'))

    async def test_complete_and_repeat_confirmation(self):
        await self.fill()
        cb = self.callback('confirm_registration')
        await self.call(reg.confirm_registration, cb)
        await self.call(reg.confirm_registration, cb)
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)
        result = report(self.path)
        self.assertEqual(result['registrations_started'], 1)
        self.assertEqual(result['registrations_completed'], 1)
        self.assertEqual(result['unfinished'], [])
        self.assertEqual({r['step'] for r in self.rows() if r['event_name']=='registration_step_completed'},
                         {'team_name', 'team_size', 'captain_name', 'phone', 'comment'})
        journal = str(self.rows())
        for secret in ['private-team', 'private-name', '+998901234567', 'private-comment']:
            self.assertNotIn(secret, journal)

    async def test_repeat_start_keeps_attempt_and_answers(self):
        await self.call(reg.register_from_event, self.callback('register_event_50'))
        await self.call(reg.reg_team_name, self.message('Test team'))
        before = await self.state.get_data()
        await self.call(reg.register_from_event, self.callback('register_event_50'))
        self.assertEqual(before, await self.state.get_data())
        self.assertEqual(report(self.path)['registrations_started'], 1)

    async def test_all_cancel_paths(self):
        for fn, cb in [(reg.reg_cancel, 'reg_cancel'), (reg.cancel_registration, 'cancel_registration'),
                       (common.cmd_cancel, None)]:
            await self.call(reg.register_from_event, self.callback('register_event_50'))
            await self.call(fn, self.callback(cb) if cb else self.message('/cancel'))
        self.assertEqual(len([r for r in self.rows() if r['event_name']=='registration_cancelled']), 3)
        self.assertEqual(report(self.path)['unfinished'], [])

    async def test_restart_keeps_journal_not_drafts(self):
        await self.call(reg.register_from_event, self.callback('register_event_50'))
        await self.call(reg.reg_team_name, self.message('Team'))
        attempt = (await self.state.get_data())['attempt_id']
        self.analytics = Analytics(self.path)
        self.state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=42, user_id=42))
        await self.call(reg.confirm_registration, self.callback('confirm_registration'))
        pending = report(self.path)['unfinished']
        self.assertEqual(pending[0]['attempt_id'], attempt)
        self.assertEqual(pending[0]['step'], 'team_name')
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 0)
        await self.call(reg.register_from_event, self.callback('register_event_50'))
        self.assertNotEqual((await self.state.get_data())['attempt_id'], attempt)

    async def test_write_failure_does_not_block_booking(self):
        await self.fill()
        self.analytics.path = str(Path(self.tmp.name) / 'missing' / 'fail.sqlite')
        await self.call(reg.confirm_registration, self.callback('confirm_registration'))
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)

    async def test_disabled_analytics(self):
        self.analytics = None
        await self.fill()
        await self.call(reg.confirm_registration, self.callback('confirm_registration'))
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)

    async def test_start_deeplink_and_transport_dedup(self):
        msg = self.message('/start event_50')
        await common.cmd_start(msg, self.db, [], self.analytics)
        await common.cmd_start(msg, self.db, [], self.analytics)
        self.assertEqual(report(self.path)['bot_starts'], 1)
        cards = [r for r in self.rows() if r['event_name']=='event_card_sent']
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['event_id'], 50)
        self.assertEqual(report(self.path)['registrations_started'], 0)

    async def test_menu_select_event_and_edit_keep_attempt(self):
        await self.call(reg.start_registration, self.message('📝 Регистрация'))
        attempt = (await self.state.get_data())['attempt_id']
        for fn, text in [(reg.reg_team_name,'Team'), (reg.reg_team_size,'4'),
                         (reg.reg_captain_name,'Captain'), (reg.reg_phone,'+998901234567'), (reg.reg_comment,'-')]:
            await self.call(fn, self.message(text))
        await self.call(reg.reg_pick_event, self.callback('reg_pick_event_50'))
        self.assertEqual(report(self.path)['unfinished'][0]['event_id'], 50)
        await self.call(reg.edit_registration, self.callback('edit_registration'))
        self.assertEqual((await self.state.get_data())['attempt_id'], attempt)
        self.assertEqual(await self.state.get_state(), RegistrationState.team_name.state)

    async def test_rejected_enums_and_init_failure(self):
        self.analytics.record('phone-secret', 42, key='test')
        self.assertEqual(self.rows(), [])
        broken = Analytics(Path(self.tmp.name) / 'missing' / 'db.sqlite')
        self.assertFalse(broken.enabled)
        broken.record('bot_started', 42, key='test')

    async def test_report_does_not_create_missing_db(self):
        absent = Path(self.tmp.name) / 'absent.sqlite'
        with self.assertRaises(sqlite3.OperationalError):
            report(absent)
        self.assertFalse(absent.exists())

    async def test_menu_message_replay_after_restart_is_deduplicated(self):
        msg = self.message('📝 Регистрация')
        await self.call(reg.start_registration, msg)
        await self.call(reg.start_registration, msg)
        self.state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=42, user_id=42))
        await self.call(reg.start_registration, msg)
        self.assertEqual(report(self.path)['registrations_started'], 1)

    async def test_journal_lock_does_not_block_business_write(self):
        await self.fill()
        with closing(sqlite3.connect(self.path)) as lock:
            lock.execute('BEGIN EXCLUSIVE')
            await self.call(reg.confirm_registration, self.callback('confirm_registration'))
            lock.rollback()
        self.assertEqual(self.business.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)

    async def test_previous_values_and_contact_are_tracked(self):
        self.db.get_last_registration_by_telegram = lambda _: dict(
            team_name='private-team', team_size=5, captain_name='private-name',
            phone='+998901234567', comment='private-comment')
        await self.call(reg.register_from_event, self.callback('register_event_50'))
        for fn, value in [(reg.reg_use_prev_team, 'reg_use_prev_team'),
                          (reg.reg_use_prev_size, 'reg_use_prev_size'),
                          (reg.reg_use_prev_captain, 'reg_use_prev_captain')]:
            await self.call(fn, self.callback(value))
        contact = self.message()
        contact.contact = SimpleNamespace(phone_number='998901234567')
        await self.call(reg.reg_phone_contact, contact)
        await self.call(reg.reg_use_prev_comment, self.callback('reg_use_prev_comment'))
        await self.call(reg.confirm_registration, self.callback('confirm_registration'))
        self.assertEqual(report(self.path)['registrations_completed'], 1)
        self.assertEqual(len([r for r in self.rows() if r['event_name']=='registration_step_completed']), 5)

    async def test_card_send_error_not_counted(self):
        cb = self.callback('show_event_50')
        cb.message.answer.side_effect = RuntimeError('test')
        with self.assertRaises(RuntimeError):
            await self.call(common.show_event_detail, cb)
        self.assertEqual(self.rows(), [])

    async def test_handler_failure_safe_code_without_exception_text(self):
        await self.fill()
        self.db.create_registration = lambda **kw: (_ for _ in ()).throw(RuntimeError('private-failure'))
        with self.assertRaises(RuntimeError):
            await self.call(reg.confirm_registration, self.callback('confirm_registration'))
        self.assertEqual(self.rows()[-1]['result'], 'handler_error')
        self.assertNotIn('private-failure', str(self.rows()))

    async def test_step_dedup_and_reedit_revision(self):
        await self.fill()
        data = await self.state.get_data()
        from analytics import emit
        emit(self.analytics, 'registration_step_completed', 42, data, 'phone')
        self.assertEqual(len([r for r in self.rows() if r['step']=='phone']), 1)
        await self.call(reg.edit_registration, self.callback('edit_registration'))
        await self.call(reg.reg_team_name, self.message('Team again'))
        self.assertEqual(report(self.path)['unfinished'][0]['step'], 'team_name')


if __name__ == '__main__':
    unittest.main()
