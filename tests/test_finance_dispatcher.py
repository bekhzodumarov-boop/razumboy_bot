"""Actual aiogram routing and FSM, synthetic updates; Telegram transport offline."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import Update, Message, User
from aiogram.client.session.base import BaseSession

from finance import FinanceStore
from handlers.finance_admin import create_router, FinanceState
from test_finance import fixture


class Offline(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
    async def close(self): pass
    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ == 'getMe':
            return User(id=1,is_bot=True,first_name='Test',username='OfflineTestBot')
        if method.__api_method__ == 'answerCallbackQuery': return True
        if method.__api_method__ in ('sendMessage','sendDocument'):
            return Message(message_id=1000+len(self.calls),date=datetime.now(timezone.utc),
                           chat={'id':method.chat_id,'type':'private'},text=getattr(method,'text',None))
        raise AssertionError('No outbound transport allowed')
    async def stream_content(self,*args,**kwargs):
        raise AssertionError('No network')
        yield b''


class FinanceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'business.sqlite'
        fixture(self.path)
        self.db = SimpleNamespace(db_path=str(self.path))
        self.transport = Offline()
        self.bot = Bot(token='1:'+ 'offline_placeholder'.ljust(35,'x'),session=self.transport)
        self.addAsyncCleanup(self.bot.session.close)
        self.dp = Dispatcher(storage=MemoryStorage(),events_isolation=SimpleEventIsolation())
        self.dp.include_router(create_router())
        self.addAsyncCleanup(self.dp.storage.close)
        self.addAsyncCleanup(self.dp.fsm.events_isolation.close)
        self.seq = 0
        self.store = FinanceStore(self.path)

    async def feed(self,text=None,callback=None,user=42,admins=None,chat_type='private'):
        self.seq += 1
        message = dict(message_id=self.seq,date=int(datetime.now(timezone.utc).timestamp()),
                       chat={'id':user if chat_type=='private' else -100,'type':chat_type},
                       from_user={'id':user,'is_bot':False,'first_name':'Test'},text=text)
        if text and text.startswith('/'):
            message['entities']=[{'type':'bot_command','offset':0,'length':len(text.split()[0])}]
        if callback:
            update=Update(update_id=self.seq,callback_query={'id':str(self.seq),'chat_instance':'offline',
                         'from_user':message['from_user'],'message':message,'data':callback})
        else:
            update=Update(update_id=self.seq,message=message)
        return await self.dp.feed_update(self.bot,update,db=self.db,admin_ids=[42,43] if admins is None else admins)

    def button(self,prefix):
        for call in reversed(self.transport.calls):
            markup=getattr(call,'reply_markup',None)
            for row in getattr(markup,'inline_keyboard',[]):
                for b in row:
                    if b.callback_data and b.callback_data.startswith(prefix): return b.callback_data
        raise AssertionError('Missing button: '+prefix)

    def output(self):
        return '\n'.join(str(getattr(c,'text','') or '') for c in self.transport.calls)

    async def open_game(self,event=50):
        await self.feed(text='👥 Явка')
        await self.choose_price(event=event)
        return self.store.snapshot(event)['teams'][0]['id']

    async def confirm(self,user=42):
        action=self.button('af:save:')
        await self.feed(callback=action,user=user)
        return action

    async def test_attendance_explicit_confirm_persists_and_double_click_safe(self):
        t=await self.open_game()
        await self.feed(callback=f'af:att:{t}')
        await self.feed(text='5')
        self.assertIsNone(self.store.team(t)['actual_players'])
        action=await self.confirm()
        await self.feed(callback=action)
        self.assertEqual(FinanceStore(self.path).team(t)['actual_players'],5)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM finance_audit').fetchone()[0],2)
        self.assertIn('устарела',self.output())
        self.assertEqual(self.store.snapshot(50)['registered_players'],29)

    async def test_private_admin_only_including_forged_callback_and_revoked_midform(self):
        before=len(self.transport.calls)
        await self.feed(text='👥 Явка',user=99)
        await self.feed(callback='af:g:50',user=99)
        await self.feed(text='👥 Явка',chat_type='group')
        self.assertFalse('Заявки:' in self.output())
        self.assertEqual(len(self.transport.calls),before+1)
        self.assertEqual(self.store.games()[0]['id'],51)
        t=await self.open_game()
        await self.feed(callback=f'af:att:{t}')
        await self.feed(text='5')
        action=self.button('af:save:')
        await self.feed(callback=action,admins=[])
        self.assertIsNone(self.store.team(t)['actual_players'])
        await self.feed(callback=action,chat_type='group')
        self.assertIsNone(self.store.team(t)['actual_players'])

    async def test_expense_add_rename_exclude_and_distribution_does_not_reduce_result(self):
        await self.open_game()
        dinner=self.store.snapshot(50)['expenses'][0]
        await self.feed(callback=f"af:expense:{dinner['id']}")
        self.assertIn('500 000 сум',self.output())
        await self.feed(text='450000')
        await self.confirm()
        await self.feed(callback='af:newcost:50')
        await self.feed(text='Распечатка & материалы')
        await self.feed(text='50000')
        await self.confirm()
        expense=self.store.snapshot(50)['expenses'][-1]
        await self.feed(callback=f"af:rename:{expense['id']}")
        await self.feed(text='Печать карточек')
        await self.confirm()
        await self.feed(callback=f"af:exclude:{expense['id']}")
        await self.confirm()
        farruh=next(x for x in self.store.snapshot(50)['expenses'] if x['template_key']=='farruh')
        await self.feed(callback=f"af:expense:{farruh['id']}")
        await self.feed(text='200000')
        await self.confirm()
        s=self.store.snapshot(50)
        self.assertEqual((s['costs_uzs'],s['distributions_uzs']),(450000,200000))
        self.assertEqual(s['result_uzs'],-450000)
        # Even a forged type-change preview cannot mutate the protected distribution.
        await self.feed(callback=f"af:kind:{farruh['id']}")
        await self.confirm()
        self.assertEqual(self.store.snapshot(50)['costs_uzs'],450000)
        self.assertIn('распределение прибыли, а не расход',self.output())

    async def test_cancel_old_confirm_and_invalid_numeric_input(self):
        t=await self.open_game()
        await self.feed(callback=f'af:att:{t}')
        await self.feed(text='-2')
        state=self.dp.fsm.get_context(bot=self.bot,chat_id=42,user_id=42)
        self.assertEqual(await state.get_state(),FinanceState.value.state)
        await self.feed(text='3')
        old=self.button('af:save:')
        await self.feed(text='/cancel')
        await self.feed(callback=old)
        self.assertIsNone(self.store.team(t)['actual_players'])
        await self.feed(callback=f'af:att:{t}')
        await self.feed(text='4')
        new=self.button('af:save:')
        await self.feed(callback=old)
        self.assertIsNone(self.store.team(t)['actual_players'])
        await self.feed(callback=new)
        self.assertEqual(self.store.team(t)['actual_players'],4)

    async def test_stale_admin_cannot_overwrite_payment_or_attendance(self):
        t=await self.open_game()
        await self.feed(callback=f'af:att:{t}')
        await self.feed(text='5')
        action=self.button('af:save:')
        self.store.attendance(t,3,0,43,'second-admin-change')
        await self.feed(callback=action)
        self.assertEqual(self.store.team(t)['actual_players'],3)
        self.assertIn('другим админом',self.output())

    async def test_storage_restart_loses_only_unconfirmed_draft(self):
        t=await self.open_game()
        await self.feed(callback=f'af:att:{t}')
        await self.feed(text='5')
        action=self.button('af:save:')
        old=self.dp.fsm.storage
        self.dp.fsm.storage=MemoryStorage()
        await old.close()
        self.addAsyncCleanup(self.dp.fsm.storage.close)
        await self.feed(callback=action)
        self.assertIsNone(self.store.team(t)['actual_players'])
        self.assertIn('устарела',self.output())

    def latest(self):
        return next(c for c in reversed(self.transport.calls) if c.__api_method__=='sendMessage')

    async def choose_price(self,choice='70000',event=50):
        await self.feed(callback=f'af:open:{event}')
        prefix=self.button('af:pricepick:').rsplit(':',1)[0]
        await self.feed(callback=prefix+':'+choice)
        if choice=='other':
            await self.feed(text='85000')

    def payment_audits(self):
        with self.store.connect() as c:
            return c.execute("SELECT COUNT(*) FROM finance_audit WHERE action='payment_breakdown'").fetchone()[0]

    async def test_entire_preview_flow_price_counts_single_confirm_report_and_csv(self):
        from finance_preview import create_preview_dispatcher
        await self.dp.storage.close()
        await self.dp.fsm.events_isolation.close()
        self.dp=create_preview_dispatcher(self.db,[42])
        self.addAsyncCleanup(self.dp.storage.close)
        self.addAsyncCleanup(self.dp.fsm.events_isolation.close)
        t=await self.open_game()
        self.assertEqual(self.store.snapshot(50)['settings']['ticket_uzs'],70000)
        await self.feed(callback=f'af:t:{t}')
        self.assertFalse(any(b.callback_data.startswith('af:pay:') for row in self.latest().reply_markup.inline_keyboard for b in row))
        await self.feed(text='Узум 2\nКлик 4\nИтого 6')
        screen=self.latest()
        self.assertIn('Uzum: 2 чел. / 140 000 сум',screen.text)
        self.assertIn('Click: 4 чел. / 280 000 сум',screen.text)
        self.assertIn('Payme: 0 чел. / 0 сум',screen.text)
        self.assertIn('Перевод на карту: 0 чел. / 0 сум',screen.text)
        self.assertIn('Наличные: 0 чел. / 0 сум',screen.text)
        self.assertIn('Итого: 6 чел. / 420 000 сум',screen.text)
        self.assertEqual([b.text for row in screen.reply_markup.inline_keyboard for b in row],['✅ Подтвердить','Отмена'])
        self.assertEqual(self.payment_audits(),0)
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)
        action=await self.confirm()
        await self.feed(callback=action)
        s=self.store.snapshot(50)
        self.assertEqual((s['paid_players'],s['income_uzs']),(6,420000))
        self.assertIsNone(self.store.team(t)['actual_players'])
        self.assertEqual(self.payment_audits(),1)
        labels=[b.text for row in self.latest().reply_markup.inline_keyboard for b in row]
        self.assertTrue(any('Следующая команда' in x for x in labels))
        self.assertTrue(any('К списку команд' in x for x in labels))
        self.assertIn('📊 Итоги игры',labels)
        await self.feed(callback='af:report:50')
        self.assertIn('Поступления: <b>420 000 сум</b>',self.latest().text)
        await self.feed(callback='af:csv:50')
        self.assertTrue(any(c.__api_method__=='sendDocument' for c in self.transport.calls))

    async def test_corrected_text_revokes_previous_confirm_and_replaces_saved_methods(self):
        t=await self.open_game()
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 2\nКлик 4')
        old=self.button('af:save:')
        await self.feed(text='Payme 3')
        new=self.button('af:save:')
        await self.feed(callback=old)
        self.assertEqual(self.payment_audits(),0)
        await self.feed(callback=new)
        self.assertEqual(self.store.snapshot(50)['income_uzs'],210000)
        await self.feed(text='Click 1')
        await self.confirm()
        p=self.store.team(t)['payments']
        self.assertEqual(p['payme']['players'],0)
        self.assertEqual(p['click']['amount_uzs'],70000)
        self.assertEqual(self.payment_audits(),2)

    async def test_invalid_correction_and_cancel_leave_existing_payment_untouched(self):
        t=await self.open_game()
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Нал 2')
        await self.confirm()
        before=self.store.team(t)['payments']
        await self.feed(text='Клик 4')
        old=self.button('af:save:')
        await self.feed(text='Узум 2\nПейми')
        self.assertIn('В строке “Пейми” не указано количество',self.latest().text)
        await self.feed(callback=old)
        self.assertEqual(self.store.team(t)['payments'],before)
        await self.feed(text='Узум 6')
        cancelled=self.button('af:save:')
        cancel=self.button('af:paycancel:')
        await self.feed(callback=cancel)
        await self.feed(callback=cancelled)
        self.assertEqual(self.store.team(t)['payments'],before)
        await self.feed(text='Payme 0')
        await self.confirm()
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)

    async def test_price_presets_custom_no_confirmation_and_no_retroactive_change(self):
        t=await self.open_game()
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 2')
        await self.confirm()
        for choice,expected in [('100000',100000),('other',85000),('70000',70000)]:
            await self.choose_price(choice)
            self.assertEqual(self.store.snapshot(50)['settings']['ticket_uzs'],expected)
            self.assertIn('Выберите команду',self.latest().text)
            self.assertFalse(any(b.callback_data.startswith('af:save:') for row in self.latest().reply_markup.inline_keyboard for b in row))
            self.assertEqual(self.store.snapshot(50)['income_uzs'],140000)
        await self.choose_price('other')
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Payme 2')
        self.assertIn('170 000 сум',self.latest().text)
        await self.confirm()
        self.assertEqual(self.store.snapshot(50)['income_uzs'],170000)

    async def test_old_payment_and_price_buttons_cannot_start_old_flow(self):
        t=await self.open_game()
        await self.feed(callback=f'af:t:{t}')
        state=self.dp.fsm.get_context(bot=self.bot,chat_id=42,user_id=42)
        prior=await state.get_data()
        for action in (f'af:pay:{t}:uzum','af:amount:old','af:price:50:70000','af:save:old'):
            await self.feed(callback=action)
            self.assertEqual(await state.get_state(),FinanceState.quick.state)
            self.assertEqual(await state.get_data(),prior)
        self.assertEqual(self.payment_audits(),0)
        await self.feed(text='Uzum 2 = 130000')
        self.assertIn('указана сумма',self.latest().text)
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)

    async def test_price_and_team_change_between_preview_and_confirmation(self):
        t=await self.open_game()
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 6')
        action=self.button('af:save:')
        self.store.ticket(50,100000,1,43,'second-admin-price')
        await self.feed(callback=action)
        self.assertEqual(self.payment_audits(),0)
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 6')
        action=self.button('af:save:')
        self.store.attendance(t,5,0,43,'second-admin-attendance')
        await self.feed(callback=action)
        self.assertEqual(self.payment_audits(),0)
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 6')
        self.assertIn('Оплативших 6, а пришло 5',self.latest().text)
        await self.feed(text='Узум 5')
        await self.confirm()
        self.assertEqual(self.store.snapshot(50)['income_uzs'],500000)

    async def test_payment_confirmation_requires_private_current_admin_and_fresh_context(self):
        t=await self.open_game()
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Клик 3')
        action=self.button('af:save:')
        await self.feed(callback=action,admins=[])
        await self.feed(callback=action,chat_type='group')
        await self.feed(callback=action,user=99)
        self.assertEqual(self.payment_audits(),0)
        await self.feed(callback='af:g:50')
        await self.feed(callback=action)
        self.assertEqual(self.payment_audits(),0)

    async def test_stale_price_button_and_concurrent_price_choice(self):
        await self.feed(text='👥 Явка')
        await self.feed(callback='af:open:50')
        old=self.button('af:pricepick:')
        await self.feed(callback='af:open:51')
        await self.feed(callback=old)
        self.assertIsNone(self.store.snapshot(50)['settings']['ticket_uzs'])
        self.store.ticket(51,85000,0,43,'other-admin-price')
        await self.feed(callback=self.button('af:pricepick:'))
        self.assertEqual(self.store.snapshot(51)['settings']['ticket_uzs'],85000)
