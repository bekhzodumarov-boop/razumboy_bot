"""Optional authenticated read-only dashboard server, separate from bot polling."""
import base64
from datetime import datetime, timedelta, timezone
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
from export_snapshot import snapshot
from live_sources import meta_insights, SourceUnavailable
ROOT=Path(__file__).with_name('web')
FILES={'/':'index.html','/index.html':'index.html','/style.css':'style.css','/app.mjs':'app.mjs','/model.mjs':'model.mjs','/seed.json':'seed.json'}
class Service:
    def __init__(self,env=None):
        self.env=dict(os.environ if env is None else env)
        user=self.env.get('DASHBOARD_USERNAME','');password=self.env.get('DASHBOARD_PASSWORD','')
        if not user or ':' in user or len(password)<24:raise ValueError('Configure dashboard username and password (24+ characters)')
        self.expected='Basic '+base64.b64encode((user+':'+password).encode()).decode()
        self.cache={};self.lock=threading.Lock()
    def authorized(self,header):
        return isinstance(header,str) and hmac.compare_digest(header.encode(),self.expected.encode())
    def payload(self):
        today=datetime.now(timezone(timedelta(hours=5))).date();since=today.replace(day=1).isoformat();until=today.isoformat()
        def bot():
            path=self.env.get('DB_PATH')
            if not path:raise SourceUnavailable('Bot database is not configured')
            return snapshot(path,date_from=since,date_to=until,analytics_path=self.env.get('DASHBOARD_ANALYTICS_PATH') or None)
        def meta():
            return meta_insights(token=self.env.get('META_ACCESS_TOKEN'),account_id=self.env.get('META_AD_ACCOUNT_ID'),api_version=self.env.get('META_GRAPH_VERSION'),since=since,until=until)
        out={}
        for name,fetch,ttl in [('bot',bot,60),('meta',meta,900)]:
            with self.lock:
                prior=self.cache.get(name)
                if prior and time.monotonic()-prior['at']<ttl and prior['day']==until:out[name]=prior['result'];continue
                try:result={'status':'connected','fetched_at':datetime.now(timezone.utc).isoformat(),'data':fetch()}
                except SourceUnavailable as e:result={'status':'unavailable','message':str(e),'data':None}
                except Exception:result={'status':'unavailable','message':name+' source could not be read','data':None}
                self.cache[name]={'at':time.monotonic(),'day':until,'result':result};out[name]=result
        return {'as_of':datetime.now(timezone.utc).isoformat(),'period':{'from':since,'to':until},'sources':out}
def handler_for(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if not service.authorized(self.headers.get('Authorization')):
                self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="RAZUMBOY Intelligence", charset="UTF-8"');self.send_header('Cache-Control','no-store');self.end_headers();return
            path=urlsplit(self.path).path
            if path=='/api/live':body=json.dumps(service.payload(),ensure_ascii=False).encode();mime='application/json; charset=utf-8'
            elif path in FILES:
                file=ROOT/FILES[path];body=file.read_bytes();mime='text/javascript' if file.suffix=='.mjs' else (mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'none'");self.end_headers();self.wfile.write(body)
    return Handler
if __name__=='__main__':
    service=Service();ThreadingHTTPServer((os.environ.get('DASHBOARD_HOST','127.0.0.1'),int(os.environ.get('DASHBOARD_PORT',os.environ.get('PORT','8080')))),handler_for(service)).serve_forever()
