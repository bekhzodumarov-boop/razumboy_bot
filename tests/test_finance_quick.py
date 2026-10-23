"""Counts-only payment calculations, confirmation transactions and concurrency."""
import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from finance import FinanceStore, FinanceError, parse_payment_lines, format_report
from test_finance import fixture


class QuickPaymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'quick.sqlite'
        fixture(self.path)
        self.f = FinanceStore(self.path)
        self.f.prepare(50)
        self.t = self.f.snapshot(50)['teams'][0]['id']
        self.f.ticket(50,70000,0,42,'seed-ticket')

    def write(self,text,revision=0,price_revision=1,operation='confirm-operation'):
        rows,total = parse_payment_lines(text)
        return self.f.batch_payment(self.t,rows,total,revision,price_revision,42,operation)

    def test_russian_latin_aliases_optional_total_and_missing_count(self):
        rows,total = parse_payment_lines('Узум 2\nКлик 4\nИтого 6')
        self.assertEqual((rows['uzum']['players'],rows['click']['players'],total),(2,4,6))
        for text in ('Uzum 2; Payme 1; Click 1; Перевод на карту 1; Наличные 1',
                     'Узум 2; Пейми 1; Клик 1; карта 1; нал 1'):
            rows,total = parse_payment_lines(text)
            self.assertIsNone(total)
            self.assertEqual(set(rows),{'uzum','payme','click','card','cash'})
        with self.assertRaisesRegex(FinanceError,'В строке “Пейми” не указано количество'):
            parse_payment_lines('Узум 2\nПейми')

    def test_readonly_preview_zero_methods_unknown_attendance_and_confirm(self):
        rows,total = parse_payment_lines('Узум 2\nКлик 4\nИтого 6')
        before = self.path.read_bytes()
        preview = self.f.preview_payments(self.t,rows,total,0,1)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual([p['amount_uzs'] for p in preview['payments']],[140000,0,280000,0,0])
        self.assertEqual(self.f.snapshot(50)['income_uzs'],0)
        self.write('Узум 2\nКлик 4\nИтого 6')
        s = FinanceStore(self.path).snapshot(50)
        self.assertEqual((s['paid_players'],s['income_uzs']),(6,420000))
        self.assertIsNone(self.f.team(self.t)['actual_players'])
        self.assertEqual(s['actual_players'],0)
        self.assertEqual(s['unknown_teams'],9)

    def test_complete_replacement_idempotency_and_zero_reset(self):
        self.write('Узум 2\nКлик 4')
        self.write('Узум 2\nКлик 4')
        self.assertEqual(self.f.team(self.t)['revision'],1)
        self.write('Payme 3',revision=1,operation='replace-operation')
        payments = self.f.team(self.t)['payments']
        self.assertEqual(payments['uzum']['players'],0)
        self.assertEqual(payments['click']['amount_uzs'],0)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],210000)
        self.write('Payme 0',revision=2,operation='zero-operation')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],0)

    def test_invalid_lines_amount_overrides_and_bad_totals_never_write(self):
        for text in ('Узум 2\nКлик 4\nИтого 5','Узум 2\nUzum 1','Пейми',
                     'Узум -2','Клик 1.5','Узум 2\nнеизвестно 4','Итого 6',
                     'Узум 2\nИтого 2\nИтого 2','Узум 2 = 130000'):
            with self.subTest(text=text), self.assertRaises(FinanceError):
                self.write(text)
        self.assertEqual(self.f.team(self.t)['payments'],{})
        with self.assertRaises(FinanceError):
            self.f.batch_payment(self.t,{'cash':{'players':1,'amount_uzs':1}},None,0,1,42,'forged-amount')

    def test_known_attendance_limit_and_revisions_are_checked_again_at_save(self):
        rows,total = parse_payment_lines('Узум 6')
        self.f.preview_payments(self.t,rows,total,0,1)
        self.f.attendance(self.t,5,0,43,'change-attendance')
        with self.assertRaises(FinanceError):self.write('Узум 6')
        with self.assertRaises(FinanceError):self.write('Узум 6',revision=1)
        self.write('Узум 5',revision=1)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],350000)

    def test_price_change_does_not_reprice_saved_payments_and_stales_preview(self):
        self.write('Узум 2')
        self.f.ticket(50,85000,1,43,'change-price')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],140000)
        with self.assertRaises(FinanceError):self.write('Клик 2',revision=1,operation='stale-price')
        self.write('Клик 2',revision=1,price_revision=2,operation='new-price')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],170000)

    def test_missing_price_and_audit_failure_roll_back_all_methods(self):
        with self.f.connect() as c:
            c.execute('UPDATE finance_games SET ticket_uzs=NULL WHERE event_id=50')
        with self.assertRaises(FinanceError):self.write('Узум 2')
        with self.f.connect() as c:
            c.execute('UPDATE finance_games SET ticket_uzs=70000 WHERE event_id=50')
        with self.assertRaises(FinanceError):self.write('Узум 2',operation='bad')
        self.assertEqual(self.f.team(self.t)['payments'],{})
        self.assertEqual(self.f.team(self.t)['revision'],0)

    def test_two_confirmations_with_same_revision_only_one_wins(self):
        rows,total = parse_payment_lines('Клик 3')
        def save(actor):
            try:
                FinanceStore(self.path).batch_payment(self.t,rows,total,0,1,actor,f'concurrent-{actor}')
                return True
            except FinanceError:return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(save,[42,43])),1)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],210000)

    def test_report_keeps_unknown_attendance_payments_out_of_known_unpaid_count(self):
        self.write('Узум 6')
        other = self.f.snapshot(50)['teams'][1]['id']
        self.f.attendance(other,3,0,42,'known-attendance')
        self.f.payment(other,'cash',1,70000,1,42,'known-payment')
        report = format_report(self.f.snapshot(50))
        self.assertIn('без отметки оплаты: 2 (включая возможные льготы)',report)
        self.assertIn('Оплативших отмечено: 7',report)
        self.assertIn('Поступления: <b>490 000 сум</b>',report)
