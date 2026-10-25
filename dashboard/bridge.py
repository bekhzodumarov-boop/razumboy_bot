"""Authenticated read-only bridge; no bot imports and no database writes."""
from datetime import datetime, timedelta, timezone
import hmac
from http.server import BaseHTTPRequestHandler
import json
import threading
import time
from urllib.parse import urlsplit
from export_snapshot import snapshot

class Bridge:
    def __init__(self, db_path, token, analytics_path=None):
        if not token or len(token)<32:raise ValueError('A 32+ character bridge token is required')
        self.db_path=db_path;self.token=token;self.analytics_path=analytics_path
        self.lock=threading.Lock();self.cached=None;self.cached_at=0
    def authorized(self,value):
        return isinstance(value,str) and hmac.compare_digest(value.encode(),('Bearer '+self.token).encode())
    def read(self):
        with self.lock:
            if self.cached and time.monotonic()-self.cached_at<30:return self.cached
            self.cached=snapshot(self.db_path,analytics_path=self.analytics_path)
            self.cached_at=time.monotonic();return self.cached

def handler_for(bridge, healthy=lambda:True):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/health':
                status=200 if healthy() else 503;body={'ok':status==200}
            elif path!='/snapshot':status=404;body={'error':'not_found'}
            elif not bridge.authorized(self.headers.get('Authorization')):status=401;body={'error':'unauthorized'}
            else:
                try:status=200;body=bridge.read()
                except Exception:status=503;body={'error':'snapshot_unavailable'}
            raw=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
    return Handler
