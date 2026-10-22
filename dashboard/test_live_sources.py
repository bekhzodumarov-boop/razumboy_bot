import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from live_sources import meta_insights
from server import Service
class LiveTests(unittest.TestCase):
    def test_tokens_headers_and_click_types(self):
        seen=[]
        def open_(req,timeout):
            seen.append(req)
            return BytesIO(json.dumps({'data':[{'spend':'18.95','clicks':'1800','inline_link_clicks':'1486','outbound_clicks':[{'action_type':'outbound_click','value':'1000'}]}]}).encode())
        r=meta_insights(token='secret',account_id='123',api_version='v1.0',since='2026-10-17',until='2026-10-22',opener=open_)
        self.assertNotIn('secret',seen[0].full_url);self.assertEqual(seen[0].get_header('Authorization'),'Bearer secret')
        self.assertEqual(r['daily_rows'][0]['inline_link_clicks'],1486);self.assertEqual(r['daily_rows'][0]['clicks'],1800);self.assertEqual(r['daily_rows'][0]['outbound_clicks'],1000)
        self.assertNotIn('secret',json.dumps(r))
    def test_missing_access_fails_closed(self):
        with self.assertRaises(ValueError):Service({})
        s=Service({'DASHBOARD_USERNAME':'reader','DASHBOARD_PASSWORD':'x'*24})
        self.assertFalse(s.authorized(None));self.assertFalse(s.authorized('Basic invalid'))
        self.assertTrue(s.authorized('Basic '+base64.b64encode(b'reader:'+b'x'*24).decode()))
        r=s.payload();self.assertEqual(r['sources']['bot']['status'],'unavailable');self.assertEqual(r['sources']['meta']['status'],'unavailable');self.assertNotIn('x'*24,json.dumps(r))
    def test_untrusted_pagination_url_ignored(self):
        seen=[];responses=[{'data':[], 'paging':{'next':'https://evil.invalid/?token=secret','cursors':{'after':'cursor'}}},{'data':[]}]
        def open_(req,timeout):seen.append(req.full_url);return BytesIO(json.dumps(responses.pop(0)).encode())
        meta_insights(token='secret',account_id='123',api_version='v1.0',since='2026-10-17',until='2026-10-22',opener=open_)
        self.assertEqual(len(seen),2);self.assertTrue(all(u.startswith('https://graph.facebook.com/v1.0/act_123/') for u in seen))

class HTTPBoundaryTests(unittest.TestCase):
    def test_all_routes_require_auth_and_api_has_no_store(self):
        from http.server import ThreadingHTTPServer
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        import threading
        from server import handler_for
        s=Service({'DASHBOARD_USERNAME':'reader','DASHBOARD_PASSWORD':'x'*24})
        http=ThreadingHTTPServer(('127.0.0.1',0),handler_for(s))
        worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
        try:
            origin='http://127.0.0.1:'+str(http.server_port)
            for path in ('/','/seed.json','/api/live'):
                with self.assertRaises(HTTPError) as ctx:urlopen(origin+path,timeout=2)
                self.assertEqual(ctx.exception.code,401)
            with urlopen(Request(origin+'/api/live',headers={'Authorization':s.expected}),timeout=2) as r:
                self.assertEqual(r.headers['Cache-Control'],'no-store')
                data=json.load(r)
                self.assertEqual(data['sources']['bot']['status'],'unavailable')
                self.assertNotIn('x'*24,json.dumps(data))
        finally:http.shutdown();http.server_close();worker.join()
