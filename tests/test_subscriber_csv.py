from contextlib import closing
from types import SimpleNamespace
import sqlite3
import unittest
from unittest.mock import AsyncMock, Mock

from handlers.admin import subs_export_csv


class SubscriberCsvTests(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_rows_with_and_without_username(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('''CREATE TABLE profiles (username TEXT,first_name TEXT,last_name TEXT,
                gender TEXT,age TEXT,phone TEXT,telegram_id INTEGER,created_at TEXT)''')
            conn.executemany('INSERT INTO profiles VALUES (?,?,?,?,?,?,?,?)',[
                ('offline_test','Synthetic',None,None,None,None,1,'2026-01-01'),
                (None,'Synthetic',None,None,None,None,2,'2026-01-01')])
            rows = conn.execute('SELECT * FROM profiles').fetchall()
        db = SimpleNamespace(get_all_subscriber_profiles=Mock(return_value=rows))
        callback = SimpleNamespace(from_user=SimpleNamespace(id=42),answer=AsyncMock(),
                    message=SimpleNamespace(answer_document=AsyncMock()))
        # Telegram delivery is a mock; no personal list is written or sent anywhere.
        await subs_export_csv(callback,db,[42])
        callback.message.answer_document.assert_awaited_once()
        payload = callback.message.answer_document.call_args.kwargs['document'].data.decode('utf-8-sig')
        self.assertIn('@offline_test',payload)
        self.assertNotIn('@None',payload)
        self.assertEqual(len(payload.splitlines()),3)
        callback.answer.assert_awaited_once()

    async def test_export_remains_admin_only(self):
        db = SimpleNamespace(get_all_subscriber_profiles=Mock())
        callback = SimpleNamespace(from_user=SimpleNamespace(id=1),answer=AsyncMock(),
                    message=SimpleNamespace(answer_document=AsyncMock()))
        await subs_export_csv(callback,db,[])
        db.get_all_subscriber_profiles.assert_not_called()
        callback.message.answer_document.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
