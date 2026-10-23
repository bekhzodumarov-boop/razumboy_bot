"""One-message payment parsing and atomic replacement, synthetic data only."""
import tempfile
import unittest
from pathlib import Path

from finance import FinanceStore, FinanceError, parse_payment_lines
from test_finance import fixture


class QuickPaymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'quick.sqlite'
        fixture(self.path)
        self.f=FinanceStore(self.path)
        self.f.prepare(50)
        self.t=self.f.snapshot(50)['teams'][0]['id']
        self.f.attendance(self.t,6,0,42,'seed-attendance')
        self.f.ticket(50,70000,0,42,'seed-ticket')

    def write(self,text,revision=1,price_revision=1,operation='quick-operation'):
        rows,total=parse_payment_lines(text)
        return self.f.batch_payment(self.t,rows,total,revision,price_revision,42,operation)

    def test_russian_english_aliases_custom_amount_and_optional_total(self):
        rows,total=parse_payment_lines('Узум 2\nКлик 4\nИтого 6')
        self.assertEqual((rows['uzum']['players'],rows['click']['players'],total),(2,4,6))
        rows,total=parse_payment_lines('Uzum: 2 = 130 000; Payme 1; Перевод на карту 1; Наличные 2')
        self.assertIsNone(total)
        self.assertEqual(rows['uzum']['amount_uzs'],130000)
        self.assertEqual(set(rows),{'uzum','payme','card','cash'})

    def test_replace_all_methods_report_persists_and_retry_does_not_duplicate(self):
        self.f.payment(self.t,'payme',4,280000,1,42,'prior-payment')
        self.write('Узум 2\nКлик 4\nИтого 6',revision=2)
        s=FinanceStore(self.path).snapshot(50)
        self.assertEqual((s['paid_players'],s['income_uzs']),(6,420000))
        self.assertEqual(self.f.team(self.t)['payments']['payme']['players'],0)
        self.write('Узум 2\nКлик 4\nИтого 6',revision=2)
        self.assertEqual(self.f.team(self.t)['revision'],3)
        with self.f.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM finance_audit WHERE action='payment_breakdown'").fetchone()[0],1)
        self.write('Нал 6 = 400000',revision=3,operation='correction-operation')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],400000)
        self.assertEqual(self.f.team(self.t)['payments']['uzum']['players'],0)

    def test_invalid_text_never_writes_partial_payments(self):
        for text in ['Узум 2\nКлик 4\nИтого 5','Узум 2\nUzum 1',
                     'Узум -2','Клик 1.5','Узум 2\nнеизвестно 4','Итого 6',
                     'Узум 2\nИтого 2\nИтого 2','Узум 2\nКлик 4\nЛишняя строка']:
            with self.subTest(text=text), self.assertRaises(FinanceError): self.write(text)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],0)
        self.assertEqual(self.f.team(self.t)['revision'],1)

    def test_over_attendance_bad_amount_and_stale_revisions_roll_back(self):
        for text,revision,price_revision in [('Узум 2\nКлик 5',1,1),
                ('Узум 2 = 0\nКлик 4',1,1),('Узум 2',0,1),('Узум 2',1,0)]:
            with self.subTest(text=text), self.assertRaises(FinanceError):
                self.write(text,revision,price_revision)
        self.assertEqual(self.f.team(self.t)['payments'],{})
        self.assertEqual(self.f.team(self.t)['revision'],1)

    def test_missing_price_requires_explicit_amount_and_unknown_attendance_rejected(self):
        with self.f.connect() as c:
            c.execute('UPDATE finance_games SET ticket_uzs=NULL WHERE event_id=50')
        with self.assertRaises(FinanceError): self.write('Узум 2\nКлик 4 = 250000')
        self.assertEqual(self.f.team(self.t)['payments'],{})
        self.write('Узум 2 = 130000\nКлик 4 = 250000')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],380000)
        other=self.f.snapshot(50)['teams'][1]['id']
        rows,total=parse_payment_lines('Узум 1 = 70000')
        with self.assertRaises(FinanceError): self.f.batch_payment(other,rows,total,0,1,42,'unknown-attendance')

    def test_zero_reset_and_audit_failure_are_atomic(self):
        self.write('Узум 2\nКлик 4')
        rows,total=parse_payment_lines('Наличные 6')
        with self.assertRaises(FinanceError):
            self.f.batch_payment(self.t,rows,total,2,1,42,'bad')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],420000)
        self.write('Узум 0\nИтого 0',revision=2,operation='reset-payments')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],0)
