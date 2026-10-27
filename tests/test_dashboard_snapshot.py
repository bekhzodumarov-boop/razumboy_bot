"""Cross-source regression: read-only finance export and historical attribution."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'dashboard'))
from export_snapshot import snapshot
from finance import FinanceStore
from analytics import Analytics
from admin_digest import format_digest
from test_finance import fixture


class SnapshotTests(unittest.TestCase):
    def test_finance_matches_ledger_without_mutation_or_private_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bot.sqlite'
            fixture(path)
            f = FinanceStore(path)
            f.prepare(50)
            f.ticket(50,70000,0,42,'ticket-test')
            t = f.snapshot(50)['teams'][0]
            f.attendance(t['id'],5,0,42,'attendance-test')
            f.batch_payment(t['id'],{'cash':{'players':5}},5,1,1,42,'payments-test')
            f.add(50,'Dinner','cost',50000,42,'expense-test')
            f.add(50,'Partner','distribution',20000,42,'distribution-test')
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = snapshot(path)
            ledger = result['events'][0]['finance']
            self.assertEqual(ledger['actual_players'],5)
            self.assertEqual(ledger['unknown_teams'],7)
            self.assertEqual(ledger['income_uzs'],350000)
            self.assertEqual(ledger['costs_uzs'],50000)
            self.assertEqual(ledger['balance_uzs'],280000)
            self.assertEqual(ledger['by_method']['cash']['players'],5)
            self.assertIsNone(result['events'][0]['attended'])
            self.assertIsNone(result['events'][1]['finance'])
            self.assertNotIn('actor_id',json.dumps(result))
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_all_period_sources_include_old_attempt_and_missing_journal_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bot.sqlite'
            fixture(path)
            journal = Analytics(str(path)+'.analytics.sqlite')
            for name in ('registration_started','registration_completed'):
                journal.record(name,123456789,key=name,event_id=50,attempt_id='old',source='instagram')
            with journal.connect() as c:
                c.execute("UPDATE funnel_events SET timestamp='2026-10-01T00:00:00.000Z'")
            result = snapshot(path,analytics_path=journal.path)
            self.assertEqual(result['events'][0]['sources']['instagram']['registration_completed'],1)
            self.assertNotIn('123456789',json.dumps(result))
            self.assertIsNone(snapshot(path,analytics_path=str(path)+'.missing')['events'][0]['funnel'])

    def test_source_matches_account_game_and_booking_time_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bot.sqlite'
            fixture(path)
            import sqlite3
            with sqlite3.connect(path) as c:
                c.execute('CREATE TABLE users(id INTEGER,telegram_id INTEGER)')
                c.execute('INSERT INTO users VALUES(1,123456789)')
                c.execute('ALTER TABLE registrations ADD COLUMN user_id INTEGER')
                c.execute('ALTER TABLE registrations ADD COLUMN created_at TEXT')
                c.execute("UPDATE registrations SET user_id=1,created_at='2026-10-01 00:00:00' WHERE id=1")
                c.execute("UPDATE registrations SET user_id=1,created_at='2026-10-21 00:00:00' WHERE id=2")
            journal=Analytics(str(path)+'.analytics.sqlite')
            for name in ('registration_started','registration_completed'):
                journal.record(name,123456789,key=name,event_id=50,attempt_id='one',source='instagram')
            with journal.connect() as c:
                c.execute("UPDATE funnel_events SET timestamp='2026-10-01T00:00:01.000Z'")
            result=snapshot(path,analytics_path=journal.path)
            self.assertEqual(result['events'][0]['teams'][0]['source'],'instagram')
            self.assertIsNone(result['events'][0]['teams'][1]['source'])
            self.assertNotIn('123456789',json.dumps(result))

