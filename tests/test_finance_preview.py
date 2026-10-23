import tempfile
import unittest
from pathlib import Path

from finance import FinanceStore
from finance_preview import check_preview_identity, seed_demo


class PreviewTests(unittest.TestCase):
    def test_production_bot_environment_and_paths_rejected(self):
        for username, env, path in [
            ('Razumboy_Bot','staging','/data/razumboy-finance-preview-v2.sqlite'),
            ('Razumboy_Test_Bot','production','/data/razumboy-finance-preview-v2.sqlite'),
            ('Razumboy_Test_Bot','staging','/data/razumboy.db')]:
            with self.assertRaises(ValueError): check_preview_identity(username,env,path)
        check_preview_identity('Razumboy_Test_Bot','staging','/data/razumboy-finance-preview-v2.sqlite')

    def test_demo_is_synthetic_repeatable_and_new_attempt_preserves_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo.sqlite'
            first=seed_demo(path)
            f=FinanceStore(path)
            s=f.snapshot(first)
            self.assertEqual((s['registered_teams'],s['registered_players']),(8,29))
            with f.connect() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],8)
                self.assertTrue(all(r[0]<0 for r in c.execute('SELECT telegram_id FROM users')))
            t=s['teams'][0]
            f.attendance(t['id'],5,0,42,'preview-test-attendance')
            self.assertEqual(seed_demo(path),first)
            self.assertEqual(f.snapshot(first)['actual_players'],5)
            second=seed_demo(path,fresh=True)
            self.assertNotEqual(first,second)
            self.assertEqual(f.snapshot(second)['unknown_teams'],8)
            self.assertEqual(f.snapshot(first)['actual_players'],5)


class PreviewEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_menu_variants_and_start_replace_keyboard(self):
        from finance_preview import create_preview_dispatcher
        from test_finance_dispatcher import Offline
        from aiogram import Bot
        from aiogram.types import Update
        from datetime import datetime, timezone
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo.sqlite'
            seed_demo(path)
            dp=create_preview_dispatcher(SimpleNamespace(db_path=str(path)),[42])
            self.addAsyncCleanup(dp.storage.close)
            self.addAsyncCleanup(dp.fsm.events_isolation.close)
            session=Offline()
            bot=Bot(token='1:'+'offline_placeholder'.ljust(35,'x'),session=session)
            self.addAsyncCleanup(bot.session.close)
            for index,text in enumerate(['⚙ Панель администратора','⚙️ Панель администратора','/start'],1):
                update=Update(update_id=index,message={'message_id':index,'date':datetime.now(timezone.utc),
                    'chat':{'id':42,'type':'private'},'from_user':{'id':42,'is_bot':False,'first_name':'Test'},'text':text,
                    **({'entities':[{'type':'bot_command','offset':0,'length':6}]} if text=='/start' else {})})
                before=len(session.calls)
                await dp.feed_update(bot,update)
                self.assertEqual(len(session.calls),before+1)
                self.assertIn('Тест явки',session.calls[-1].text)
                self.assertEqual(session.calls[-1].reply_markup.keyboard[0][0].text,'👥 Явка')

    async def test_unknown_user_gets_clear_denial_without_access_or_seed_data(self):
        from finance_preview import create_preview_dispatcher
        from test_finance_dispatcher import Offline
        from aiogram import Bot
        from aiogram.types import Update
        from datetime import datetime, timezone
        from types import SimpleNamespace
        dp=create_preview_dispatcher(SimpleNamespace(db_path='must-not-open.sqlite'),[42])
        self.addAsyncCleanup(dp.storage.close)
        self.addAsyncCleanup(dp.fsm.events_isolation.close)
        session=Offline()
        bot=Bot(token='1:'+'offline_placeholder'.ljust(35,'x'),session=session)
        self.addAsyncCleanup(bot.session.close)
        for index,text in enumerate(['⚙ Панель администратора','👥 Явка','/start'],1):
            update=Update(update_id=index,message={'message_id':index,'date':datetime.now(timezone.utc),
                'chat':{'id':99,'type':'private'},'from_user':{'id':99,'is_bot':False,'first_name':'Test'},'text':text,
                **({'entities':[{'type':'bot_command','offset':0,'length':6}]} if text=='/start' else {})})
            await dp.feed_update(bot,update)
            self.assertIn('не настроен',session.calls[-1].text)
            self.assertNotIn('Альфа',session.calls[-1].text)
        self.assertFalse(Path('must-not-open.sqlite').exists())
