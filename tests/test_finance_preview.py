import tempfile
import unittest
from pathlib import Path

from finance import FinanceStore
from finance_preview import check_preview_identity, seed_demo


class PreviewTests(unittest.TestCase):
    def test_production_bot_environment_and_paths_rejected(self):
        for username, env, path in [
            ('Razumboy_Bot','staging','/data/razumboy-finance-preview.sqlite'),
            ('Razumboy_Test_Bot','production','/data/razumboy-finance-preview.sqlite'),
            ('Razumboy_Test_Bot','staging','/data/razumboy.db')]:
            with self.assertRaises(ValueError): check_preview_identity(username,env,path)
        check_preview_identity('Razumboy_Test_Bot','staging','/data/razumboy-finance-preview.sqlite')

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
