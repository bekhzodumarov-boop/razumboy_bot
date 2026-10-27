import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from bridge import Bridge,handler_for
class BridgeTests(unittest.TestCase):
    def test_http_auth_privacy_no_database_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'bot.db'
            with sqlite3.connect(db) as conn:
                today=__import__('datetime').date.today().isoformat()
                conn.executescript('CREATE TABLE events(id INTEGER,title TEXT,event_date TEXT); CREATE TABLE registrations(id INTEGER,event_id INTEGER,team_name TEXT,team_size INTEGER,status TEXT,phone TEXT);')
                conn.execute('INSERT INTO events VALUES(50,?,?)',('Disco',today));conn.execute('INSERT INTO registrations VALUES(1,50,?,4,?,?)',('Team','confirmed','PRIVATE_PHONE'))
            before=hashlib.sha256(db.read_bytes()).hexdigest();token='x'*48
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Bridge(db,token)))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                origin='http://127.0.0.1:'+str(server.server_port)
                with urlopen(origin+'/health',timeout=2) as r:self.assertEqual(r.status,200)
                for header in (None,'Bearer wrong'):
                    with self.assertRaises(HTTPError) as err:urlopen(Request(origin+'/snapshot',headers={'Authorization':header} if header else {}),timeout=2)
                    self.assertEqual(err.exception.code,401)
                with urlopen(Request(origin+'/snapshot',headers={'Authorization':'Bearer '+token}),timeout=2) as r:
                    raw=r.read().decode();data=json.loads(raw)
                    self.assertNotIn('PRIVATE_PHONE',raw);self.assertNotIn(token,raw);self.assertEqual(data['events'][0]['teams'][0]['size'],4);self.assertIsNone(data['events'][0]['attended'])
                self.assertEqual(before,hashlib.sha256(db.read_bytes()).hexdigest())
            finally:server.shutdown();server.server_close();thread.join()
    def test_missing_token_fails_before_bot_start(self):
        with self.assertRaises(ValueError):Bridge('/not-created',None)
