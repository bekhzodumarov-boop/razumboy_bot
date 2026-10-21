"""Subscriber phone routing with synthetic updates, isolated SQLite and no HTTP."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Update

from handlers import common
from states import SubscribeState
import sqlite_fixture as fixtures
import test_dispatcher as offline


class SubscriberPhoneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = fixtures.TestDatabase(str(Path(self.tmp.name) / 'test.sqlite'))
        self.db.qualify_referral = Mock(return_value=None)
        self.session = offline.OfflineSession()
        self.bot = Bot(token='1:' + 'offline_placeholder'.ljust(35, 'x'), session=self.session)
        self.addAsyncCleanup(self.session.close)
        self.dp = Dispatcher(db=self.db, admin_ids=[])
        self.addAsyncCleanup(self.dp.storage.close)
        router = Router()
        router.message.register(common.subscribe_first_name, SubscribeState.first_name)
        router.message.register(common.subscribe_phone_contact, SubscribeState.phone, F.contact)
        router.message.register(common.subscribe_phone, SubscribeState.phone)
        self.dp.include_router(router)
        self.state = self.dp.fsm.get_context(bot=self.bot, chat_id=42, user_id=42)
        await self.state.set_state(SubscribeState.phone)
        await self.state.update_data(first_name='Synthetic')
        self.sequence = 0

    async def feed(self, **content):
        self.sequence += 1
        await self.dp.feed_update(self.bot, Update(update_id=self.sequence, message={
            'message_id': self.sequence, 'date': datetime.now(timezone.utc),
            'chat': {'id': 42, 'type': 'private'},
            'from_user': {'id': 42, 'is_bot': False, 'first_name': 'Synthetic'},
            **content,
        }))

    def contact(self, user_id=42, phone='998901234567'):
        return {'phone_number': phone, 'first_name': 'Synthetic', 'user_id': user_id}

    async def assert_saved(self):
        self.assertEqual(self.db.get_subscriber_profile(42)['phone'], '+998901234567')
        self.assertIsNone(await self.state.get_state())
        self.db.qualify_referral.assert_called_once_with(42)
        keyboard = self.session.calls[-1].reply_markup.keyboard
        self.assertFalse(any(button.request_contact for row in keyboard for button in row))
        self.assertTrue(any(button.text == '🎯 Ближайшие игры' for row in keyboard for button in row))

    async def assert_rejected(self):
        self.assertIsNone(self.db.get_subscriber_profile(42))
        self.assertEqual(await self.state.get_state(), SubscribeState.phone.state)
        self.db.qualify_referral.assert_not_called()
        self.assertTrue(self.session.calls[-1].reply_markup.keyboard[0][0].request_contact)

    async def test_name_offers_contact_button(self):
        await self.state.set_state(SubscribeState.first_name)
        await self.feed(text='Synthetic')
        self.assertEqual(await self.state.get_state(), SubscribeState.phone.state)
        button = self.session.calls[-1].reply_markup.keyboard[0][0]
        self.assertEqual(button.text, '📱 Поделиться своим номером')
        self.assertTrue(button.request_contact)

    async def test_manual_formatted_number(self):
        await self.feed(text=' +998 (90) 123-45-67 ')
        await self.assert_saved()

    async def test_manual_without_plus(self):
        await self.feed(text='998901234567')
        await self.assert_saved()

    async def test_own_contact(self):
        await self.feed(contact=self.contact())
        await self.assert_saved()

    async def test_foreign_contact_then_manual_retry(self):
        await self.feed(contact=self.contact(user_id=99))
        await self.assert_rejected()
        await self.feed(text='+998901234567')
        await self.assert_saved()

    async def test_contact_without_owner(self):
        await self.feed(contact=self.contact(user_id=None))
        await self.assert_rejected()

    async def test_invalid_own_contact(self):
        await self.feed(contact=self.contact(phone='+1234'))
        await self.assert_rejected()

    async def test_invalid_manual_data(self):
        for value in ('abc', '+99890123', '+9989012345678', '+79991234567',
                      '+998９０１２３４５６７', '+998901234567 trailing'):
            with self.subTest(value=value):
                await self.feed(text=value)
                await self.assert_rejected()

    async def test_non_text_message(self):
        await self.feed()
        await self.assert_rejected()

    async def test_referral_qualification_preserved(self):
        self.db.qualify_referral.return_value = 99
        self.db.get_referral_stats = Mock(return_value={
            'current_count': 1, 'next_threshold': 3, 'next_label': 'Reward'})
        self.db.check_and_issue_reward = Mock(return_value=None)
        await self.feed(contact=self.contact())
        self.db.qualify_referral.assert_called_once_with(42)
        self.db.check_and_issue_reward.assert_called_once_with(99)
        self.assertEqual(self.session.calls[-1].chat_id, 99)
