from contextlib import closing
"""Synthetic ledger data only; no credentials, live database or provider calls."""
import concurrent.futures
import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from finance import FinanceStore, FinanceError, TEMPLATES, format_report, export_csv, parse_integer


def fixture(path):
    with closing(sqlite3.connect(path)) as c, c:
        c.executescript('''
        CREATE TABLE events(id INTEGER PRIMARY KEY,title TEXT,event_date TEXT);
        CREATE TABLE registrations(id INTEGER PRIMARY KEY,event_id INTEGER,team_name TEXT,team_size INTEGER,status TEXT);
        INSERT INTO events VALUES(50,'Test <quiz>','2026-10-22'),(51,'Next','2026-10-25');
        INSERT INTO registrations VALUES(1,50,'Отчаянные',4,'confirmed'),(2,50,'Волосик',2,'confirmed'),
        (3,50,'Принцессы',6,'confirmed'),(4,50,'Котичные',3,'confirmed'),(5,50,'Панды',6,'confirmed'),
        (6,50,'No show A',3,'confirmed'),(7,50,'No show B',3,'confirmed'),(8,50,'No show C',2,'confirmed'),
        (9,51,'Отчаянные',5,'confirmed'),(10,50,'Cancelled',2,'cancelled');
        ''')


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'test.sqlite'
        fixture(self.path)
        self.f = FinanceStore(self.path)
        self.f.prepare(50)
        self.seq = 0

    def op(self):
        self.seq += 1
        return f'test-operation-{self.seq}'

    def test_additive_idempotent_init_preserves_bookings_unknown_not_zero(self):
        with closing(sqlite3.connect(self.path)) as c, c:
            before = c.execute('SELECT * FROM registrations').fetchall()
        self.f.prepare(50)
        FinanceStore(self.path).prepare(50)
        s = self.f.snapshot(50)
        self.assertEqual((s['registered_teams'],s['registered_players']), (8,29))
        self.assertEqual(s['unknown_teams'],9)
        self.assertEqual(s['actual_players'],0)
        self.assertEqual(s['income_uzs'],0)
        self.assertEqual(s['pending_expenses'],6)
        self.assertEqual(len(s['expenses']),len(TEMPLATES))
        self.assertTrue(all(x['amount_uzs'] is None for x in s['expenses']))
        with closing(sqlite3.connect(self.path)) as c, c:
            self.assertEqual(before,c.execute('SELECT * FROM registrations').fetchall())
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_actual_example_five_teams_twenty_people_not_29(self):
        s = self.f.snapshot(50)
        for t, count in zip(s['teams'],[5,2,3,2,8,0,0,0,0]):
            self.f.attendance(t['id'],count,0,42,self.op())
        s = self.f.snapshot(50)
        self.assertEqual((s['arrived_teams'],s['actual_players']), (5,20))
        self.assertEqual(s['registered_players'],29)
        self.assertEqual(s['unknown_teams'],0)
        self.assertIn('5 команд / 20 игроков',format_report(s))

    def test_split_payments_discount_correction_and_duplicate_operation(self):
        t = self.f.snapshot(50)['teams'][0]['id']
        self.f.attendance(t,5,0,42,self.op())
        op = self.op()
        self.f.payment(t,'uzum',2,150000,1,42,op)
        self.f.payment(t,'uzum',2,150000,1,42,op)
        self.f.payment(t,'cash',3,300000,2,43,self.op())
        s = self.f.snapshot(50)
        self.assertEqual(s['income_uzs'],450000)
        self.assertEqual(s['paid_players'],5)
        self.f.payment(t,'cash',2,180000,3,43,self.op())
        self.assertEqual(self.f.snapshot(50)['income_uzs'],330000)
        self.f.payment(t,'uzum',0,0,4,42,self.op())
        self.assertEqual(self.f.snapshot(50)['paid_players'],2)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],180000)

    def test_invalid_payments_and_attendance_roll_back(self):
        t = self.f.snapshot(50)['teams'][0]['id']
        with self.assertRaises(FinanceError):
            self.f.payment(t,'cash',1,100000,0,42,self.op())
        self.f.attendance(t,2,0,42,self.op())
        self.f.payment(t,'cash',2,200000,1,42,self.op())
        for fn in [lambda:self.f.payment(t,'payme',1,100000,2,42,self.op()),
                   lambda:self.f.attendance(t,1,2,42,self.op()),
                   lambda:self.f.attendance(t,None,2,42,self.op()),
                   lambda:self.f.payment(t,'cash',1,-1,2,42,self.op()),
                   lambda:self.f.payment(t,'cash',0,100,2,42,self.op()),
                   lambda:self.f.payment(t,'invalid',1,100,2,42,self.op())]:
            with self.assertRaises(FinanceError): fn()
        self.assertEqual(self.f.team(t)['revision'],2)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],200000)

    def test_two_admins_only_one_stale_revision_wins(self):
        t = self.f.snapshot(50)['teams'][0]['id']
        def change(count):
            try:
                FinanceStore(self.path).attendance(t,count,0,42+count,f'concurrent-{count}')
                return True
            except FinanceError:
                return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            result = list(pool.map(change,[3,4]))
        self.assertEqual(sum(result),1)
        self.assertEqual(self.f.team(t)['revision'],1)

    def test_expenses_vary_by_game_rename_exclude_custom_and_transfer_kind(self):
        self.f.prepare(51)
        s = self.f.snapshot(50)
        dinner, transfer = s['expenses'][0], s['expenses'][-1]
        self.f.expense(dinner['id'],450000,'confirmed',0,42,self.op())
        self.f.expense(transfer['id'],200000,'confirmed',0,42,self.op())
        self.f.add(50,'Распечатка','cost',50000,42,self.op())
        self.f.rename_expense(dinner['id'],'Ужин для команды',1,42,self.op())
        s = self.f.snapshot(50)
        self.assertEqual((s['costs_uzs'],s['distributions_uzs'],s['result_uzs'],s['balance_uzs']),
                         (500000,200000,-500000,-700000))
        self.assertEqual(self.f.snapshot(51)['costs_uzs'],0)
        self.assertEqual(self.f.snapshot(51)['expenses'][0]['title'],'Ужин на игре')
        with self.assertRaises(FinanceError):
            self.f.expense_kind(transfer['id'],'cost',1,42,self.op())
        self.assertEqual(self.f.snapshot(50)['costs_uzs'],500000)
        self.f.expense(dinner['id'],0,'excluded',2,42,self.op())
        s = self.f.snapshot(50)
        self.assertEqual(s['costs_uzs'],50000)
        self.f.expense(dinner['id'],510000,'confirmed',3,42,self.op())
        self.assertEqual(self.f.snapshot(50)['costs_uzs'],560000)
        with self.f.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM finance_audit').fetchone()[0],6)

    def test_price_no_retroactive_repricing_and_walkins(self):
        self.f.ticket(50,100000,0,42,self.op())
        op = self.op()
        self.f.add(50,'Walk in','team',None,42,op)
        self.f.add(50,'Walk in','team',None,42,op)
        t = self.f.snapshot(50)['teams'][-1]
        self.f.attendance(t['id'],1,0,42,self.op())
        self.f.payment(t['id'],'click',1,70000,1,42,self.op())
        self.f.ticket(50,120000,1,42,self.op())
        self.assertEqual(self.f.snapshot(50)['income_uzs'],70000)
        self.assertEqual(self.f.snapshot(50)['registered_teams'],8)
        self.assertEqual(len(self.f.snapshot(50)['teams']),10)

    def test_csv_safe_formulas_unknowns_and_no_contacts(self):
        self.f.add(50,'=HYPERLINK("test")','cost',100,42,self.op())
        data = export_csv(self.f.snapshot(50)).decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(data)))
        self.assertTrue(any(r[1].startswith("'=HYPERLINK") for r in rows))
        self.assertTrue(any(r[2]=='не отмечена' and r[3]=='' for r in rows))
        self.assertNotIn('phone',data)
        self.assertIn('&lt;quiz&gt;',format_report(self.f.snapshot(50)))

    def test_integer_input_bounds(self):
        self.assertEqual(parse_integer('500,000',10**12),500000)
        self.assertEqual(parse_integer('1 000 000',10**12),1000000)
        for value in ['-1','1.5','1e3','１２３','',None,'1/2']:
            with self.assertRaises(FinanceError): parse_integer(value,500)
        for value in [True,1.5,-1,501]:
            with self.assertRaises(FinanceError): self.f.attendance(1,value,0,42,self.op())

    def test_all_five_methods_and_persistent_totals(self):
        t=self.f.snapshot(50)['teams'][0]['id']
        self.f.attendance(t,5,0,42,self.op())
        for revision,method in enumerate(('uzum','payme','click','card','cash'),1):
            self.f.payment(t,method,1,100000,revision,42,self.op())
        s=FinanceStore(self.path).snapshot(50)
        self.assertEqual(s['income_uzs'],500000)
        self.assertEqual(s['paid_players'],5)
        self.assertTrue(all(p['amount_uzs']==100000 for p in s['by_method'].values()))

    def test_actual_database_schema_preserves_all_legacy_rows(self):
        from sqlite_fixture import TestDatabase
        path=Path(self.tmp.name)/'real_schema.sqlite'
        TestDatabase(str(path))
        with closing(sqlite3.connect(path)) as c, c:
            c.execute("INSERT INTO events(id,title,event_date,event_time,location) VALUES(50,'Synthetic','2099-01-01','19:00','Test')")
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            before={t:c.execute('SELECT * FROM "'+t+'" ORDER BY rowid').fetchall() for t in tables}
        f=FinanceStore(path)
        f.prepare(50)
        f.add(50,'Walk in','team',None,42,'real-schema-team')
        t=f.snapshot(50)['teams'][0]['id']
        f.attendance(t,2,0,42,'real-schema-attendance')
        f.payment(t,'card',2,180000,1,42,'real-schema-payment')
        with closing(sqlite3.connect(path)) as c, c:
            after={t:c.execute('SELECT * FROM "'+t+'" ORDER BY rowid').fetchall() for t in tables}
            self.assertEqual(before,after)
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
