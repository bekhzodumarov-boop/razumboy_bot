import hashlib
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from release_backup import release_archive
from bridge import Bridge,handler_for

class BackupTests(unittest.TestCase):
    def test_integrity_hashes_and_separate_admin_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'business.sqlite'
            with sqlite3.connect(db) as c:c.execute('CREATE TABLE private(value TEXT)');c.execute("INSERT INTO private VALUES('synthetic-private-record')")
            before=db.read_bytes()
            archive=release_archive(db,Path(tmp)/'backups')
            self.assertEqual(before,db.read_bytes())
            with zipfile.ZipFile(archive) as z:
                manifest=json.loads(z.read('manifest.json'))
                record=manifest['databases'][0]
                self.assertEqual(hashlib.sha256(z.read(record['file'])).hexdigest(),record['sha256'])
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Bridge(db,'s'*40),backup_path=archive,backup_token='b'*40))
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                url=f'http://127.0.0.1:{server.server_port}/ops/release-backup'
                for token in ('','s'*40):
                    with self.assertRaises(HTTPError) as e:urlopen(Request(url,headers={'Authorization':'Bearer '+token}))
                    self.assertEqual(e.exception.code,404)
                with urlopen(Request(url,headers={'Authorization':'Bearer '+'b'*40})) as response:
                    self.assertEqual(response.read(),archive.read_bytes())
            finally:server.shutdown();server.server_close();t.join()
