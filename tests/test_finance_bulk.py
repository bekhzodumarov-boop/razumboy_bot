import copy
import tempfile
import unittest
from pathlib import Path
from finance import FinanceStore, FinanceError
from test_finance import fixture


class BulkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'bot.sqlite'
        fixture(self.path)
        self.f=FinanceStore(self.path)
        self.f.prepare(50)
        self.f.ticket(50,70000,0,42,'price-test')

    def test_user_example_is_preview_then_atomic_idempotent_save(self):
        text='Отчаянные 5 - 280П+70П\nВолосик 2 - 140У\nПринцессы 3 - 210Н\nКотичные 2 - 70У+70К\nПанды 8 - 560Н'
        d=self.f.preview_bulk(50,text)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],0)
        self.f.save_bulk(d,42,'bulk-test')
        self.f.save_bulk(d,42,'bulk-test')
        s=self.f.snapshot(50)
        self.assertEqual((s['actual_players'],s['paid_players'],s['income_uzs']),(20,20,1400000))
        self.assertEqual(s['by_method']['payme']['players'],5)
        self.assertEqual(s['by_method']['card']['players'],0)
        self.assertEqual(s['registered_players'],29)

    def test_ambiguous_incomplete_non_divisible_overpaid_and_unknown_rejected(self):
        for text in ['Отчаянные 5 - 400+200 переводом','Отчаянные 5 -',
                     'Отчаянные 5 - 400Н','Отчаянные 4 - 350Н',
                     'Unknown 2 - 140Н','Отчаянные 5 - 350X',
                     'Отчаянные 5 - 350Н\nОтчаянные 5 - 350Н']:
            with self.subTest(text=text),self.assertRaises(FinanceError):
                self.f.preview_bulk(50,text)
        self.assertEqual(self.f.snapshot(50)['income_uzs'],0)

    def test_stale_second_team_rolls_back_first_and_price_change_rejects(self):
        d=self.f.preview_bulk(50,'Отчаянные 5 - 350Н\nВолосик 2 - 140У')
        self.f.attendance(d['teams'][1]['team_id'],2,0,43,'other-admin')
        with self.assertRaises(FinanceError):self.f.save_bulk(d,42,'stale-bulk')
        self.assertEqual(self.f.snapshot(50)['income_uzs'],0)
        self.assertIsNone(self.f.team(d['teams'][0]['team_id'])['actual_players'])
        d=self.f.preview_bulk(50,'Отчаянные 5 - 350Н')
        self.f.ticket(50,100000,1,43,'other-price')
        with self.assertRaises(FinanceError):self.f.save_bulk(d,42,'price-stale')

    def test_alias_matches_are_unique_and_missing_methods_replace_old_values(self):
        d=self.f.preview_bulk(50,'Отчаянные 5 - 350П')
        self.f.save_bulk(d,42,'first-import')
        d=self.f.preview_bulk(50,'Отчаянные 5 - 350Н')
        self.f.save_bulk(d,42,'second-import')
        s=self.f.snapshot(50)
        self.assertEqual(s['by_method']['payme']['players'],0)
        self.assertEqual(s['by_method']['cash']['players'],5)
        self.f.add(50,'Отчаянные','team',None,42,'duplicate-name')
        with self.assertRaises(FinanceError):self.f.preview_bulk(50,'Отчаянные 5 - 350Н')
