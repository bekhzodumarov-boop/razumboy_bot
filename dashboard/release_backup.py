"""Verified release backup, made before the bot opens its business database."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
import zipfile


def release_archive(db_path, root):
    root=Path(root)/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    root.mkdir(parents=True,mode=0o700)
    records=[]
    for source in (Path(db_path),Path(str(db_path)+'.analytics.sqlite')):
        if not source.is_file():
            if source==Path(db_path):raise RuntimeError('Production database missing')
            continue
        target=root/source.name
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Backup integrity check failed')
        os.chmod(target,0o600)
        records.append({'file':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size})
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'commit':os.getenv('RAILWAY_GIT_COMMIT_SHA','unknown'),'databases':records}
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2))
    archive=root/'release.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        z.write(root/'manifest.json','manifest.json')
        for record in records:z.write(root/record['file'],record['file'])
    os.chmod(archive,0o600)
    print('RELEASE_BACKUP_VERIFIED '+json.dumps({'databases':len(records),'bytes':archive.stat().st_size}),flush=True)
    return archive
