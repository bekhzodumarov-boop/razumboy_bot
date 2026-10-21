"""Offline tests for privacy-safe admin digest. No Railway or Telegram network."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import hashlib
from html.parser import HTMLParser
from contextlib import closing
from zoneinfo import ZoneInfo

from admin_digest import format_digest, digest_enabled, split_digest, send_daily_digest
from analytics import Analytics
import scheduling


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "ra.sqlite")
        with closing(sqlite3.connect(self.path)) as db, db:
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
                self.assertEqual(jobs[-1].kwargs['id'], 'admin_daily_digest')
                self.assertEqual(jobs[-1].kwargs['max_instances'], 1)
                self.assertTrue(jobs[-1].kwargs['coalesce'])

    def test_all_games_empty_past_and_invalid_selection(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany('INSERT INTO events VALUES(?,?,?,?,?,?)',
                          [(i, f'Game {i}', '2026-10-23', '19:00', 0, 'open') for i in range(51, 58)])
            db.execute("INSERT INTO events VALUES(49,'Past','2026-10-01','19:00',0,'closed')")
        text = format_digest(Path(self.path), now=self.now)
        self.assertIn('#57', text)
        self.assertNotIn('#49', text)
        self.assertIn('0 команд', text)
        self.assertIn('#49', format_digest(self.path, event_id=49, now=self.now))
        self.assertNotIn('#50', format_digest(self.path, event_id=49, now=self.now))
        self.assertIn('Игра не найдена', format_digest(self.path, event_id=999, now=self.now))
        for bad in (0, -1, True, '50', 2**63):
            with self.assertRaises(ValueError):
                format_digest(self.path, event_id=bad, now=self.now)

    def test_24h_source_outcomes_and_readonly_files(self):
        journal = Analytics(self.path + '.analytics.sqlite')
        rows = [('registration_started', 'done', '2026-10-20T04:00:00.000Z'),
                ('registration_completed', 'done', '2026-10-20T05:00:00.000Z'),
                ('registration_started', 'open', '2026-10-21T03:00:00.000Z'),
                ('registration_started', 'excluded', '2026-10-20T03:59:59.999Z'),
                ('registration_started', 'future', '2026-10-21T04:00:00.000Z')]
        for i, (name, attempt, timestamp) in enumerate(rows):
            journal.record(name, 123456789, key=str(i), event_id=50, attempt_id=attempt,
                           source='instagram', step='start')
            with journal.connect() as db:
                db.execute('UPDATE funnel_events SET timestamp=? WHERE dedup_key=?', (timestamp, str(i)))
        paths = [Path(self.path), Path(journal.path)]
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        text = format_digest(self.path, now=self.now)
        self.assertIn('24ч: 2 / 1', text)
        self.assertIn('открытые 1', text)
        self.assertIn('instagram: 2 нач., 1 заверш.', text)
        self.assertNotIn('123456789', text)
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])

    def test_corrupt_and_locked_journal_degrade_without_leaking(self):
        path = Path(self.path + '.analytics.sqlite')
        path.write_bytes(b'corrupt private-name +998901234567')
        with self.assertLogs('admin_digest', level='WARNING') as logs:
            text = format_digest(self.path, now=self.now)
        self.assertIn('6 заявленных', text)
        self.assertNotIn('private-name', str(logs.output))
        path.unlink()
        journal = Analytics(path)
        with journal.connect() as conn:
            conn.execute('BEGIN EXCLUSIVE')
            text = format_digest(self.path, now=self.now)
            self.assertIn('временно недоступна', text)
            self.assertIn('6 заявленных', text)

    def test_long_html_split_and_uri_special_characters(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany('INSERT INTO events VALUES(?,?,?,?,?,?)',
                          [(i, '<&😀\n\u2028\u0085' * 1000, '2026-10-23', '<19:00>', 0, 'open') for i in range(51, 70)])
        new_path = Path(self.path).with_name('test # report.sqlite')
        Path(self.path).rename(new_path)
        text = format_digest(new_path, now=self.now)
        parts = split_digest(text)
        self.assertGreater(len(parts), 1)
        self.assertEqual('\n'.join(parts), text)
        class Balanced(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
            def handle_endtag(self, tag):
                assert self.tags.pop() == tag
        for part in parts:
            self.assertLessEqual(len(part.encode('utf-16-le')) // 2, 3900)
            parser = Balanced()
            parser.feed(part)
            self.assertEqual(parser.tags, [])


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_build_failure_and_recipient_isolation(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        db = SimpleNamespace(db_path='unused')
        with patch.dict(os.environ, {'ADMIN_DIGEST_ENABLED': '0'}), patch('admin_digest.format_digest') as build:
            await send_daily_digest(bot, db, [1, 2])
            build.assert_not_called()
            bot.send_message.assert_not_called()
        with patch.dict(os.environ, {'ADMIN_DIGEST_ENABLED': '1'}):
            with patch('admin_digest.format_digest', side_effect=RuntimeError('private-token')):
                with self.assertLogs('admin_digest', level='WARNING') as logs:
                    await send_daily_digest(bot, db, [1, 2])
                self.assertNotIn('private-token', str(logs.output))
            text = '\n'.join(['<b>report</b>'] * 1000)
            async def send(admin, *args, **kwargs):
                if admin == 1:
                    raise RuntimeError('private-recipient')
            bot.send_message.side_effect = send
            with patch('admin_digest.format_digest', return_value=text):
                await send_daily_digest(bot, db, [1, 1, 2])
            calls = bot.send_message.call_args_list
            self.assertEqual(sum(c.args[0] == 1 for c in calls), 1)
            self.assertEqual(sum(c.args[0] == 2 for c in calls), len(split_digest(text)))
            self.assertTrue(all(c.kwargs['parse_mode'] == 'HTML' for c in calls))


if __name__ == "__main__":
    unittest.main()
