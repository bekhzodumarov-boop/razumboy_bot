import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from marketing_dashboard.api import Settings, create_app
from marketing_dashboard.core import Store, parse_ads
from marketing_dashboard.demo import demo_csv, demo_payload
from marketing_dashboard.export_copy import export_copy


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/'analytics.db')
        self.payload = demo_payload()
        self.store.import_snapshot(self.payload)
        self.store.import_ads(demo_csv(),currency='UZS',account_timezone='Asia/Tashkent',level='ad')

    def query(self, **kwargs):
        return self.store.query('2026-10-10','2026-10-22',**kwargs)

    def test_counts_distinct_repeat_visits_and_unfinished(self):
        out = self.query()
        rows = self.payload['events']
        self.assertEqual(out['stages'][0]['events'],sum(e['name']=='bot_started' for e in rows))
        self.assertEqual(out['metrics']['unique_users'],len({e['actor'] for e in rows}))
        self.assertLess(out['stages'][0]['unique'],out['stages'][0]['events'])
        for state in ('unfinished','cancelled','superseded','technical_errors','completed'):
            self.assertGreater(out['outcomes'][state],0)
        self.assertEqual(out['metrics']['cancelled_bookings'],3)

    def test_game_source_campaign_and_first_seen_filters(self):
        all_rows=self.query()
        game=self.query(game=50)
        self.assertEqual(len(game['games']),1)
        self.assertLess(game['metrics']['teams'],all_rows['metrics']['teams'])
        self.assertIsNone(game['metrics']['spend'])
        source=self.query(source='instagram')
        self.assertGreater(source['stages'][3]['events'],0)
        self.assertIsNone(source['metrics']['teams'])
        self.assertIsNone(source['metrics']['players'])
        campaign=self.query(campaign='20001')
        self.assertIsNone(campaign['stages'][0]['events'])
        self.assertEqual(len(campaign['campaigns']),1)
        self.assertLess(self.query(first_from='2026-10-20')['metrics']['unique_users'],all_rows['metrics']['unique_users'])

    def test_window_exclusive_and_timezone(self):
        a=self.store.query('2026-10-10','2026-10-11')
        b=self.store.query('2026-10-11','2026-10-12')
        both=self.store.query('2026-10-10','2026-10-12')
        self.assertEqual(a['stages'][0]['events']+b['stages'][0]['events'],both['stages'][0]['events'])
        for bad in [('bad','2026-10-22'),('2026-10-22','2026-10-10')]:
            with self.assertRaises(ValueError): self.store.query(*bad)

    def test_snapshot_idempotence_history_regression_and_pii_rejection(self):
        before=self.query()['metrics']
        self.store.import_snapshot(self.payload)
        self.assertEqual(self.query()['metrics'],before)
        for mutate in ('delete','rewrite','pii','stream'):
            payload=copy.deepcopy(self.payload)
            if mutate=='delete':payload['events'].pop()
            if mutate=='rewrite':payload['events'][0]['source']='qr'
            if mutate=='pii':payload['events'][0]['phone']='+998901234567'
            if mutate=='stream':payload['stream']='other'
            with self.assertRaises(ValueError):self.store.import_snapshot(payload)
        self.assertEqual(self.query()['metrics'],before)

    def test_import_corrections_and_history_preservation(self):
        before=self.query()['metrics']['spend']
        text=demo_csv()
        args=dict(currency='UZS',account_timezone='Asia/Tashkent',level='ad')
        self.store.import_ads(text,**args)
        self.assertEqual(self.query()['metrics']['spend'],before)
        corrected='\n'.join(text.splitlines()[:2]).replace('45000','55000')+'\n'
        self.store.import_ads(corrected,**args)
        self.assertEqual(self.query()['metrics']['spend'],before+10000)
        self.assertEqual(len(self.query()['timeline']),12)

    def test_mixed_granularity_currency_timezone_never_double_count(self):
        before=self.query()['metrics']['spend']
        text=demo_csv().replace('30001,Музыка / 25–44,40001,Музыкальный вечер · видео',',,,').replace('30002,Квиз / Ташкент,40002,Вечер с друзьями · сторис',',,,')
        self.store.import_ads(text,currency='UZS',account_timezone='Asia/Tashkent',level='campaign')
        self.store.import_ads(demo_csv(),currency='USD',account_timezone='UTC',level='ad')
        self.assertEqual(self.query()['metrics']['spend'],before)
        self.assertEqual(self.query(level='campaign')['metrics']['spend'],before)
        self.assertIsNone(self.query(currency='EUR')['metrics']['spend'])

    def test_cost_formulas_and_unavailable_revenue_attribution(self):
        m=self.query()['metrics']
        self.assertAlmostEqual(m['cpm'],m['spend']/m['impressions']*1000)
        self.assertAlmostEqual(m['cpc'],m['spend']/m['link_clicks'])
        for key in ('reach','frequency','cpl','cost_per_player','cac','romi','roas'):
            self.assertIsNone(m[key])

    def test_csv_rejects_ambiguous_schema_dates_and_amounts(self):
        text=demo_csv()
        for bad in (text.replace('impressions','alien'),text.replace('45000','NaN'),text.replace('45000','-1'),
                    text.replace('45000','1.001'),text.replace('2026-10-10,2026-10-10','2026-10-10,2026-10-11'),
                    '\n'.join(text.splitlines()+[text.splitlines()[1]])):
            with self.assertRaises(ValueError):parse_ads(bad,'UZS','Asia/Tashkent','ad')
        with self.assertRaises(ValueError):parse_ads(text,'JPY','UTC','ad')

    def test_single_row_reach_and_missing_clicks_not_zero(self):
        text='\n'.join(demo_csv().splitlines()[:2])+'\n'
        row=parse_ads(text,'UZS','UTC','ad')[0]
        from marketing_dashboard.core import ad_metrics
        self.assertEqual(ad_metrics([row])['reach'],2800)
        row['link_clicks']=None
        self.assertIsNone(ad_metrics([row])['cpc'])

    def test_semicolon_csv_decimal_comma_and_zero_denominators(self):
        text='account_id;date_start;date_stop;campaign_id;campaign_name;spend;impressions;link_clicks\n1;2026-10-20;2026-10-20;2;Test;12,50;0;0\n'
        rows=parse_ads(text,'UZS','UTC','campaign')
        from marketing_dashboard.core import ad_metrics
        metrics=ad_metrics(rows)
        self.assertEqual(metrics['spend'],12.5)
        for key in ('ctr','cpm','cpc'):self.assertIsNone(metrics[key])

    def test_late_game_assignment_never_leaks_before_cutoff(self):
        payload=demo_payload();payload['stream']='late';payload['events']=[];payload['registrations']=[]
        base=demo_payload()['events'][0]
        attempt=hashlib.sha256(b'late-attempt').hexdigest()
        for seq,at,name,game in [(1,'2026-10-19T20:00:00Z','registration_started',None),
                                  (2,'2026-10-20T20:00:00Z','registration_step_completed',50),
                                  (3,'2026-10-21T20:00:00Z','registration_completed',50)]:
            payload['events'].append({**base,'seq':seq,'key':hashlib.sha256(str(seq).encode()).hexdigest(),
                                      'at':at,'name':name,'game':game,'attempt':attempt})
        store=Store(Path(self.tmp.name)/'late.db');store.import_snapshot(payload)
        before=store.query('2026-10-20','2026-10-21',game=50)
        self.assertEqual(before['stages'][2]['events'],0)
        after=store.query('2026-10-20','2026-10-22',game=50)
        self.assertEqual(after['stages'][2]['events'],1)
        self.assertEqual(after['outcomes']['unfinished'],1)

    def test_no_internal_identifiers_in_aggregate_response(self):
        output=json.dumps(self.query())
        for name in ('actor','attempt','dedup_key','user_id','phone','captain_name'):
            self.assertNotIn('"'+name+'"',output)
        self.assertNotIn(self.payload['events'][0]['actor'],output)


class ExportTests(unittest.TestCase):
    def test_store_refuses_bot_or_journal_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            for table in ('users','registrations','events','funnel_events'):
                path=Path(directory)/(table+'.db')
                with closing(sqlite3.connect(path)) as conn,conn:
                    conn.execute('CREATE TABLE '+table+'(id INTEGER)')
                before=hashlib.sha256(path.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):Store(path)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_isolated_export_readonly_whitelist_and_old_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);business=root/'copy # business.db';journal=root/'copy journal.db'
            with closing(sqlite3.connect(business)) as conn,conn:
                conn.execute('CREATE TABLE events(id,title,event_date,max_teams)')
                conn.execute("INSERT INTO events VALUES(50,'Quiz','2026-10-22',20)")
                conn.execute('CREATE TABLE registrations(event_id,created_at,status,team_size,phone,captain_name)')
                conn.execute("INSERT INTO registrations VALUES(50,'2026-10-19 20:00:00','confirmed',5,'private-phone','private-name')")
            with closing(sqlite3.connect(journal)) as conn,conn:
                conn.execute('CREATE TABLE funnel_events(id,timestamp,user_id,event_id,attempt_id,event_name,step,result,dedup_key)')
                conn.execute("INSERT INTO funnel_events VALUES(1,'2026-10-20T10:00:00Z',123456789,50,'attempt-private','bot_started','start','ok','private-dedup')")
            hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in (business,journal)]
            payload=export_copy(business,journal,key='synthetic-key-with-more-than-32-characters',stream='test')
            text=json.dumps(payload)
            for value in ('123456789','private-phone','private-name','attempt-private','private-dedup'):self.assertNotIn(value,text)
            self.assertEqual(payload['events'][0]['source'],'unknown')
            self.assertEqual(payload['registrations'][0]['players'],5)
            self.assertEqual(payload['registrations'][0]['day'],'2026-10-20')
            self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).hexdigest() for p in (business,journal)])
            store=Store(root/'separate.db');store.import_snapshot(payload)
            self.assertEqual(store.query('2026-10-20','2026-10-21',game=50)['metrics']['teams'],1)

    def test_analytics_backup_preserves_wal_and_never_overwrites(self):
        from marketing_dashboard.manage import backup
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=Store(root/'source.db');store.import_snapshot(demo_payload())
            digest=backup(store.path,root/'backup.db')
            self.assertEqual(len(digest),64)
            restored=Store(root/'backup.db')
            self.assertEqual(len(restored.snapshot()['events']),len(demo_payload()['events']))
            with self.assertRaises(ValueError):backup(store.path,root/'backup.db')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.settings=Settings(str(Path(self.tmp.name)/'web.db'),'synthetic-test-password-2026','https://testserver')
        self.app=create_app(self.settings)
        self.client=TestClient(self.app,base_url='https://testserver')
        self.addCleanup(self.client.close)
        self.app.state.store.import_snapshot(demo_payload())
        self.app.state.store.import_ads(demo_csv(),currency='UZS',account_timezone='Asia/Tashkent',level='ad')
        self.url='/api/dashboard?start=2026-10-10&until=2026-10-22'

    def login(self):
        response=self.client.post('/api/login',json={'password':self.settings.password},headers={'Origin':self.settings.origin})
        self.assertEqual(response.status_code,200)
        return {'Origin':self.settings.origin,'X-CSRF-Token':response.json()['csrf']}

    def test_every_data_import_export_endpoint_requires_admin(self):
        for path in (self.url,'/api/meta-template.csv','/api/campaigns.csv?start=2026-10-10&until=2026-10-22','/api/session'):
            self.assertEqual(self.client.get(path).status_code,401)
        for path in ('/api/import/meta','/api/import/telegram','/api/logout'):
            self.assertEqual(self.client.post(path,json={},headers={'Origin':self.settings.origin}).status_code,401)

    def test_secure_cookie_csrf_origin_logout(self):
        headers=self.login()
        cookie=self.client.cookies.get('razumboy_session')
        self.assertTrue(cookie)
        self.assertEqual(self.client.get(self.url).status_code,200)
        self.assertEqual(self.client.post('/api/logout',json={},headers={'Origin':self.settings.origin}).status_code,403)
        self.assertEqual(self.client.post('/api/logout',json={},headers={**headers,'Origin':'https://evil.invalid'}).status_code,403)
        self.assertEqual(self.client.post('/api/logout',json={},headers=headers).status_code,200)
        self.client.cookies.set('razumboy_session',cookie)
        self.assertEqual(self.client.get(self.url).status_code,401)

    def test_password_throttle(self):
        for _ in range(8):
            self.assertEqual(self.client.post('/api/login',json={'password':'wrong'},headers={'Origin':self.settings.origin}).status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'password':'wrong'},headers={'Origin':self.settings.origin}).status_code,429)

    def test_upload_atomic_error_does_not_echo_input_or_lose_history(self):
        headers=self.login()
        before=self.client.get(self.url).json()['metrics']
        response=self.client.post('/api/import/meta',json={'csv':'private-phone,private-token','currency':'UZS','account_timezone':'UTC','level':'ad'},headers=headers)
        self.assertEqual(response.status_code,400)
        self.assertNotIn('private-',response.text)
        self.assertEqual(before,self.client.get(self.url).json()['metrics'])
        response=self.client.post('/api/import/telegram',json={'phone':'private-phone'},headers=headers)
        self.assertEqual(response.status_code,400)
        self.assertNotIn('private-phone',response.text)

    def test_csv_formula_escape_and_security_headers(self):
        self.login()
        text=demo_csv().replace('Осенние музыкальные квизы','=HYPERLINK("bad")')
        self.app.state.store.import_ads(text,currency='UZS',account_timezone='Asia/Tashkent',level='ad')
        response=self.client.get('/api/campaigns.csv?start=2026-10-10&until=2026-10-22')
        self.assertEqual(response.status_code,200)
        self.assertIn("'=HYPERLINK",response.text)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertIn("frame-ancestors 'none'",response.headers['content-security-policy'])

    def test_invalid_filters_and_oversize_upload(self):
        headers=self.login()
        for suffix in ('&game=bad','&source=facebook','&account_timezone=Bad/Zone','&unexpected=private'):
            self.assertEqual(self.client.get(self.url+suffix).status_code,400)
        self.assertEqual(self.client.post('/api/import/meta',content='x'*(2*1024*1024+1),headers=headers).status_code,413)

    def test_secure_defaults_reject_weak_password_and_http(self):
        for settings in (Settings('unused','weak','https://localhost'),Settings('unused','long-password-for-test','http://public.example')):
            with self.assertRaises(ValueError):create_app(settings)


if __name__=='__main__':unittest.main()
