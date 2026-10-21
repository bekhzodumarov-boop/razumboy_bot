"""Offline tests for privacy-safe admin digest. No Railway or Telegram network."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from admin_digest import format_digest, digest_enabled
import scheduling


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "ra.sqlite")
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE events(id INTEGER PRIMARY KEY,title TEXT,event_date TEXT,event_time TEXT,max_teams INTEGER,status TEXT)")
            db.execute("CREATE TABLE registrations(id INTEGER PRIMARY KEY,event_id INTEGER,status TEXT,team_size INTEGER,phone TEXT)")
            db.execute("INSERT INTO events VALUES(50,'Тест <&','2026-10-22','19:00',12,'open')")
            db.execute("INSERT INTO registrations VALUES(1,50,'confirmed',6,'+998901234567')")
            db.execute("INSERT INTO registrations VALUES(2,50,'cancelled',5,'+998911111111')")
        self.now = datetime(2026,10,21,9,0,tzinfo=ZoneInfo("Asia/Tashkent"))

    def test_readonly_counts_and_privacy_without_journal(self):
        r = format_digest(self.path, now=self.now)
        self.assertIn("#50", r)
        self.assertIn("1/12 команд",r)
        self.assertIn("6 заявленных",r)
        self.assertIn("временно недоступна",r)
        self.assertNotIn("+998",r)
        self.assertIn("Тест &lt;&amp;",r)

    def test_scheduler_is_opt_in(self):
        with patch.dict(os.environ, {"ADMIN_DIGEST_ENABLED":"0","SCHEDULER_ENABLED":"1"}):
            with patch("scheduling.AsyncIOScheduler") as constructor:
                scheduling.start_scheduler(None,object(),[],0)
                self.assertEqual(constructor.return_value.add_job.call_count,7)
        with patch.dict(os.environ, {"ADMIN_DIGEST_ENABLED":"1","SCHEDULER_ENABLED":"1"}):
            with patch("scheduling.AsyncIOScheduler") as constructor:
                scheduling.start_scheduler(None,object(),[],0)
                jobs = constructor.return_value.add_job.call_args_list
                self.assertEqual(len(jobs),8)
                self.assertEqual(jobs[-1].kwargs["hour"],9)
                self.assertEqual(jobs[-1].kwargs["minute"],0)


if __name__ == "__main__":
    unittest.main()
