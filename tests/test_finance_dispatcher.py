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
        await self.feed(callback=f'af:g:{event}')
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
            self.assertEqual(c.execute('SELECT COUNT(*) FROM finance_audit').fetchone()[0],1)
        self.assertIn('устарела',self.output())
        self.assertEqual(self.store.snapshot(50)['registered_players'],29)

    async def test_payments_mixed_methods_discount_and_corrected_total(self):
        t=await self.open_game()
        self.store.attendance(t,5,0,42,'seed-attendance')
        await self.feed(callback=f'af:pay:{t}:uzum')
        await self.feed(text='2')
        await self.feed(text='150 000')
        await self.confirm()
        await self.feed(callback=f'af:pay:{t}:cash')
        await self.feed(text='3')
        await self.feed(text='300000')
        await self.confirm()
        self.assertEqual(self.store.snapshot(50)['income_uzs'],450000)
        await self.feed(callback=f'af:pay:{t}:cash')
        await self.feed(text='2')
        await self.feed(text='180000')
        await self.confirm()
        s=self.store.snapshot(50)
        self.assertEqual((s['paid_players'],s['income_uzs']),(4,330000))

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

    async def test_price_shortcut_walkin_report_and_csv(self):
        await self.open_game()
        await self.feed(callback='af:price:50')
        await self.feed(callback='af:price:50:100000')
        await self.confirm()
        await self.feed(callback='af:newteam:50')
        await self.feed(text='Walk in')
        await self.confirm()
        t=self.store.snapshot(50)['teams'][-1]['id']
        await self.feed(callback=f'af:att:{t}')
        await self.feed(text='2')
        await self.confirm()
        await self.feed(callback=f'af:pay:{t}:click')
        await self.feed(text='2')
        await self.confirm()
        await self.feed(callback='af:report:50')
        await self.feed(callback='af:csv:50')
        self.assertIn('200 000 сум',self.output())
        self.assertTrue(any(c.__api_method__=='sendDocument' for c in self.transport.calls))
        self.assertEqual(self.store.snapshot(50)['registered_players'],29)

    async def test_price_presets_and_custom_keep_existing_payment_amounts(self):
        t=await self.open_game()
        self.store.attendance(t,8,0,42,'seed-att')
        self.store.payment(t,'cash',1,90000,1,42,'seed-pay')
        for choice,expected in [('70000',70000),('100000',100000),('other',85000)]:
            await self.feed(callback='af:price:50')
            self.assertIn('70 000 сум',str(self.transport.calls[-2].reply_markup))
            await self.feed(callback=f'af:price:50:{choice}')
            if choice=='other': await self.feed(text='85000')
            await self.confirm()
            self.assertEqual(self.store.snapshot(50)['settings']['ticket_uzs'],expected)
            self.assertEqual(self.store.snapshot(50)['income_uzs'],90000)

    async def test_count_only_preview_is_not_silently_discarded_then_saved_to_report(self):
        t=await self.open_game()
        self.store.attendance(t,8,0,42,'seed-att')
        self.store.ticket(50,100000,0,42,'seed-price')
        await self.feed(callback=f'af:pay:{t}:uzum')
        await self.feed(text='1')
        action=self.button('af:save:')
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)
        await self.feed(callback=f'af:pay:{t}:payme')
        self.assertIn('Оплата еще не сохранена',self.output())
        await self.feed(callback=action)
        self.assertEqual(self.store.snapshot(50)['income_uzs'],100000)
        self.assertIn('Оплата сохранена',self.output())
        latest=self.transport.calls[-1]
        self.assertIn('100 000 сум',latest.text)
        self.assertTrue(any('Следующая команда' in b.text for row in latest.reply_markup.inline_keyboard for b in row))
        await self.feed(callback=f'af:pay:{t}:payme')
        await self.feed(text='4')
        await self.confirm()
        await self.feed(callback=f'af:pay:{t}:click')
        await self.feed(text='3')
        await self.confirm()
        await self.feed(callback='af:report:50')
        self.assertIn('Поступления: <b>800 000 сум</b>',self.transport.calls[-2].text)
        self.assertEqual((self.store.snapshot(50)['paid_players'],self.store.snapshot(50)['income_uzs']),(8,800000))

    async def test_custom_payment_amount_cancel_and_repeated_save(self):
        t=await self.open_game()
        self.store.attendance(t,3,0,42,'seed-att')
        self.store.ticket(50,100000,0,42,'seed-price')
        await self.feed(callback=f'af:pay:{t}:cash')
        await self.feed(text='2')
        old=self.button('af:save:')
        await self.feed(callback=self.button('af:amount:'))
        await self.feed(text='150000')
        await self.feed(callback=old)
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)
        action=await self.confirm()
        await self.feed(callback=action)
        self.assertEqual(self.store.snapshot(50)['income_uzs'],150000)
        await self.feed(callback=f'af:pay:{t}:cash')
        await self.feed(text='3')
        await self.feed(callback='af:cancel')
        self.assertEqual(self.store.snapshot(50)['income_uzs'],150000)
        self.assertIn('Фактическая явка',self.transport.calls[-1].text)

    async def test_preview_dispatcher_count_confirm_and_report_without_fallback(self):
        from finance_preview import create_preview_dispatcher
        await self.dp.storage.close()
        await self.dp.fsm.events_isolation.close()
        self.dp=create_preview_dispatcher(self.db,[42])
        self.addAsyncCleanup(self.dp.storage.close)
        self.addAsyncCleanup(self.dp.fsm.events_isolation.close)
        t=await self.open_game()
        self.store.attendance(t,2,0,42,'seed-att')
        self.store.ticket(50,70000,0,42,'seed-price')
        await self.feed(callback=f'af:pay:{t}:uzum')
        await self.feed(text='3')
        self.assertIn('Оплативших больше пришедших',self.output())
        await self.feed(text='2')
        await self.feed(text='готово')
        self.assertIn('Данные еще не сохранены',self.output())
        await self.confirm()
        await self.feed(callback='af:report:50')
        self.assertIn('Поступления: <b>140 000 сум</b>',self.transport.calls[-2].text)
        self.assertNotIn('Это тестовый режим',self.output())

    async def test_one_message_payment_saved_without_callback_and_visible_in_report(self):
        from finance_preview import create_preview_dispatcher
        await self.dp.storage.close()
        await self.dp.fsm.events_isolation.close()
        self.dp=create_preview_dispatcher(self.db,[42])
        self.addAsyncCleanup(self.dp.storage.close)
        self.addAsyncCleanup(self.dp.fsm.events_isolation.close)
        t=await self.open_game()
        self.store.attendance(t,6,0,42,'seed-att')
        self.store.ticket(50,70000,0,42,'seed-price')
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 2\nКлик 4\nИтого 6')
        self.seq -= 1
        await self.feed(text='Узум 2\nКлик 4\nИтого 6')
        with self.store.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM finance_audit WHERE action='payment_breakdown'").fetchone()[0],1)
        self.assertEqual((self.store.snapshot(50)['paid_players'],self.store.snapshot(50)['income_uzs']),(6,420000))
        self.assertIn('Всего оплачено: 6 чел. / 420 000 сум',self.transport.calls[-1].text)
        await self.feed(callback='af:report:50')
        self.assertIn('Поступления: <b>420 000 сум</b>',self.transport.calls[-2].text)
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Payme 6 = 400000')
        self.assertEqual(self.store.snapshot(50)['income_uzs'],400000)
        self.assertEqual(self.store.team(t)['payments']['uzum']['players'],0)

    async def test_quick_payment_errors_unauthorized_and_context_navigation(self):
        t=await self.open_game()
        self.store.attendance(t,6,0,42,'seed-att')
        self.store.ticket(50,70000,0,42,'seed-price')
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 2\nКлик 4\nИтого 5')
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)
        await self.feed(text='Узум 2\nКлик 4',user=99)
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)
        self.store.attendance(t,5,1,43,'other-admin-change')
        await self.feed(text='Узум 2\nКлик 4')
        self.assertIn('другим админом',self.output())
        self.assertEqual(self.store.snapshot(50)['income_uzs'],0)
        await self.feed(callback=f'af:t:{t}')
        await self.feed(text='Узум 2\nКлик 3')
        other=self.store.snapshot(50)['teams'][1]['id']
        await self.feed(callback=f'af:t:{other}')
        await self.feed(text='Нал 2')
        self.assertIn('Сначала укажите фактическую явку',self.output())
        self.assertEqual(self.store.team(t)['payments']['click']['players'],3)
        await self.feed(callback='af:g:50')
        await self.feed(text='Узум 1')
        self.assertEqual(self.store.snapshot(50)['income_uzs'],350000)

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
