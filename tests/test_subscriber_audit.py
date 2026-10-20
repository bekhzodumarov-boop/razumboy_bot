from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from subscriber_audit import analyze_backup, normalized_phone, open_backup


class SubscriberAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'offline-copy.sqlite'
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript('''
              CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER, phone TEXT,
                subscribed INTEGER, is_admin INTEGER, created_at TEXT, full_name TEXT);
              CREATE TABLE subscribers_profile (telegram_id INTEGER, phone TEXT, created_at TEXT, first_name TEXT);
              CREATE TABLE registrations (user_id INTEGER,event_id INTEGER,phone TEXT,status TEXT,created_at TEXT,captain_name TEXT);
              CREATE TABLE referrals (referrer_telegram_id INTEGER,referred_telegram_id INTEGER,qualified INTEGER,
                joined_at TEXT,qualified_at TEXT);
            ''')
            # Synthetic fixtures only; none are printed by the report.
            conn.executemany('INSERT INTO users VALUES (?,?,?,?,?,?,?)', [
                (1,700000001,'+998901111111',1,0,'2026-01-01','PRIVATE_MARKER'),
                (2,700000002,None,0,0,'2026-08-01','PRIVATE_MARKER'),
                (3,700000003,None,1,0,'2026-10-01','PRIVATE_MARKER'),
                (4,700000004,'bad-private-phone',1,0,'2026-01-01','PRIVATE_MARKER'),
                (5,700000005,None,1,1,'2026-01-01','PRIVATE_MARKER'),
                (6,700000006,None,2,0,'bad-private-date','PRIVATE_MARKER')])
            conn.executemany('INSERT INTO subscribers_profile VALUES (?,?,?,?)',[
                (700000001,'998 90 111-11-11','2026-01-01','PRIVATE_MARKER'),
                (700000002,'+998902222222','2026-09-01','PRIVATE_MARKER'),
                (700000004,'+998901111111','2026-01-01','PRIVATE_MARKER'),
                (799999999,'+998903333333','2026-01-01','PRIVATE_MARKER')])
            conn.executemany('INSERT INTO registrations VALUES (?,?,?,?,?,?)',[
                (1,50,'+998901111111','confirmed','2026-10-20','PRIVATE_MARKER'),
                (2,50,'+998902222222','confirmed','2026-07-23','PRIVATE_MARKER'),
                (2,51,'+998902222222','cancelled','2026-07-22','PRIVATE_MARKER'),
                (3,50,'+998904444444','confirmed','2026-04-24','PRIVATE_MARKER'),
                (3,51,'+998904444444','confirmed','2026-04-23','PRIVATE_MARKER'),
                (3,52,'+998904444444','confirmed','2026-10-21','PRIVATE_MARKER'),
                (999,50,'+998905555555','confirmed','invalid-private-date','PRIVATE_MARKER')])
            conn.executemany('INSERT INTO referrals VALUES (?,?,?,?,?)',[
                (700000001,700000002,1,'2026-09-01','2026-09-01'),
                (788888888,700000003,0,'2026-10-01',None),
                (700000001,799999999,1,'2026-01-01','2026-01-01')])
            conn.commit()

    def audit(self):
        return analyze_backup(self.path, confirmed_local_backup=True, as_of='2026-10-21T00:00:00Z')

    def test_counts_phone_normalization_and_intersections(self):
        out = self.audit()
        self.assertEqual(out['totals'], dict(users=6, subscribers_profile=4, registrations=7, referrals=3))
        self.assertEqual(out['phones']['union_unique_valid'], 5)
        self.assertEqual(out['phones']['subscribers_profile']['unique_valid'], 3)
        self.assertEqual(out['phones']['registrations']['repeated_valid_rows'], 3)
        self.assertEqual(out['phones']['pairwise_shared_unique']['subscribers_profile__registrations'], 2)
        self.assertEqual(out['account_overlaps']['users__profiles'], 3)
        self.assertEqual(out['account_overlaps']['users_profiles_registrations'], 2)
        self.assertEqual(out['anomalies']['profiles_without_user'], 1)
        self.assertEqual(out['anomalies']['registrations_without_user'], 1)
        self.assertEqual(out['anomalies']['referrals_missing_referrer'], 1)
        self.assertEqual(out['anomalies']['referrals_missing_referred'], 1)
        self.assertEqual(out['anomalies']['phones_shared_across_accounts'], 1)

    def test_captain_histograms_and_subscription_flags(self):
        out = self.audit()
        self.assertEqual(out['captains']['all_registration_rows'], dict(one=1,two=1,three_plus=1))
        self.assertEqual(out['captains']['currently_confirmed_rows'], dict(one=2,two=0,three_plus=1))
        self.assertEqual(out['subscriptions'],dict(flag_1=4,flag_0=1,invalid_or_null=1,
                                                  flag_1_without_profile=2,profiles_linked_to_flag_0=1))
        self.assertFalse(out['advertising_consent']['evidence_verified'])
        self.assertEqual(out['advertising_consent']['schema_name_hints'], 0)

    def test_activity_windows_boundaries_and_invalid_dates(self):
        out = self.audit()
        recent = out['activity']['last_90_days']
        older = out['activity']['last_180_days']
        self.assertEqual(recent['registrations'], 2)  # July 23 included, July 22 excluded.
        self.assertEqual(older['registrations'], 4)  # April 24 included, April 23 excluded.
        self.assertEqual(recent['registration_accounts'], 2)
        self.assertEqual(older['registration_accounts'], 3)
        self.assertEqual(out['invalid_or_missing_timestamps']['registrations'], 1)
        self.assertEqual(self.audit(), analyze_backup(self.path, confirmed_local_backup=True,
                         as_of='2026-10-21T05:00:00+05:00'))

    def test_report_contains_aggregates_only(self):
        output = json.dumps(self.audit())
        for value in ('PRIVATE_MARKER','+998','700000001','799999999','bad-private-phone','invalid-private-date'):
            self.assertNotIn(value, output)
        def check(value):
            if isinstance(value,dict):
                for child in value.values():
                    check(child)
            elif isinstance(value,list):
                self.assertTrue(all(isinstance(child,str) for child in value))
            else:
                self.assertIsInstance(value,(int,bool,str))
        check(self.audit())

    def test_backup_hash_and_sidecars_unchanged_and_writes_denied(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        names = sorted(p.name for p in self.path.parent.iterdir())
        self.audit()
        with open_backup(self.path, confirmed_local_backup=True) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('UPDATE users SET subscribed=0')
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('CREATE TABLE forbidden (id INTEGER)')
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()),names)

    def test_refuses_unconfirmed_missing_and_network_input(self):
        with self.assertRaises(ValueError):
            analyze_backup(self.path)
        missing = self.path.parent / 'absent.sqlite'
        with self.assertRaises(FileNotFoundError):
            analyze_backup(missing,confirmed_local_backup=True)
        self.assertFalse(missing.exists())
        for value in ('https://example.test/live.db','//server/share/data.db'):
            with self.assertRaises(ValueError):
                analyze_backup(value,confirmed_local_backup=True)

    def test_refuses_live_sidecars_and_bad_schema(self):
        for suffix in ('-wal','-shm','-journal'):
            sidecar = Path(str(self.path)+suffix)
            sidecar.touch()
            with self.assertRaises(ValueError):
                self.audit()
            sidecar.unlink()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('DROP TABLE referrals')
        with self.assertRaises(ValueError):
            self.audit()

    def test_refuses_project_database_and_views_without_reading_rows(self):
        project_db = self.path.parent / 'razumboy.db'
        project_db.write_bytes(self.path.read_bytes())
        with patch('subscriber_audit.__file__', str(self.path.parent / 'subscriber_audit.py')):
            with self.assertRaises(ValueError):
                analyze_backup(project_db,confirmed_local_backup=True)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript('ALTER TABLE users RENAME TO original_users; CREATE VIEW users AS SELECT * FROM original_users;')
        with self.assertRaises(ValueError):
            self.audit()

    def test_consent_column_is_only_a_hint_not_authorization(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('ALTER TABLE users ADD COLUMN ads_consent INTEGER DEFAULT 1')
        out = self.audit()
        self.assertEqual(out['advertising_consent']['schema_name_hints'],1)
        self.assertFalse(out['advertising_consent']['evidence_verified'])

    def test_cli_sanitized_errors_and_output(self):
        script = str(Path(__file__).resolve().parents[1]/'subscriber_audit.py')
        command = [sys.executable,script,str(self.path),'--confirm-local-backup','--as-of','2026-10-21T00:00:00Z']
        proc = subprocess.run(command,capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(proc.stdout)['totals']['users'],6)
        self.assertNotIn('PRIVATE_MARKER',proc.stdout)
        for args in ([sys.executable,script,str(self.path)],command+['--unknown','PRIVATE_MARKER'],
                     [sys.executable,script,'PRIVATE_MARKER','--confirm-local-backup'],
                     command[:-1]+['PRIVATE_MARKER']):
            proc = subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            self.assertNotIn('PRIVATE_MARKER',proc.stdout+proc.stderr)
            self.assertNotIn('Traceback',proc.stderr)

    def test_empty_database_and_phone_format_rules(self):
        with closing(sqlite3.connect(self.path)) as conn:
            for table in ('users','subscribers_profile','registrations','referrals'):
                conn.execute(f'DELETE FROM {table}')
            conn.commit()
        out = self.audit()
        self.assertTrue(all(value==0 for value in out['totals'].values()))
        self.assertEqual(out['phones']['union_unique_valid'],0)
        self.assertEqual(normalized_phone('998 (90) 111-11-11'),'+998901111111')
        for value in ('901111111','+998000000000','+1 202 555 0100','+998９０１１１１１１１',None,123):
            self.assertIsNone(normalized_phone(value))


if __name__ == '__main__':
    unittest.main()
