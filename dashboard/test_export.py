import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('export_snapshot', Path(__file__).with_name('export_snapshot.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class SnapshotTests(unittest.TestCase):
    def test_snapshot_readonly_privacy_and_registration_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'fixture.db'
            with sqlite3.connect(path) as c:
                c.executescript('''CREATE TABLE events(id INTEGER, title TEXT, event_date TEXT);
                  CREATE TABLE registrations(id INTEGER, event_id INTEGER, team_name TEXT, team_size INTEGER, status TEXT, phone TEXT, captain_name TEXT, user_id INTEGER);
                  INSERT INTO events VALUES(50, 'Disco', '22.10.2026');
                  INSERT INTO events VALUES(51, 'Next', '2026-10-25');
                  INSERT INTO registrations VALUES(1,50,'Team',4,'confirmed','PRIVATE_PHONE','PRIVATE_CAPTAIN',987654321);
                  INSERT INTO registrations VALUES(2,50,'Cancelled',8,'cancelled','PRIVATE_PHONE','PRIVATE_CAPTAIN',987654321);''')
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = mod.snapshot(path, date_from='2026-10-22', date_to='2026-10-22')
            self.assertEqual(len(result['events']), 1)
            e=result['events'][0]
            self.assertIsNone(e['attended'])
            self.assertEqual(e['teams'], [{'name':'Team','size':4,'kind':'team'}])
            self.assertEqual(e['cancelled'], 1)
            for private in ('PRIVATE_PHONE','PRIVATE_CAPTAIN','987654321','user_id','phone'):
                self.assertNotIn(private, json.dumps(result))
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaises(ValueError):
                mod.snapshot(path, date_from='2026-10-25', date_to='2026-10-22')

    def test_missing_input_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing.db'
            with self.assertRaises(sqlite3.OperationalError):
                mod.snapshot(path)
            self.assertFalse(path.exists())

if __name__ == '__main__':
    unittest.main()
