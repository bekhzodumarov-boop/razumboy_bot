"""Explicit local import/backup commands. Never reads bot config or .env."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .core import Store


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or source==destination:
        raise ValueError('Choose a new backup destination')
    # Exclusive creation prevents overwriting a concurrently created file.
    destination.touch(exist_ok=False)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=2)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Integrity check failed')
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['telegram','meta','backup'])
    parser.add_argument('--db',required=True)
    parser.add_argument('--file',required=True)
    parser.add_argument('--currency',default='UZS')
    parser.add_argument('--account-timezone',default='Asia/Tashkent')
    parser.add_argument('--level',choices=['campaign','adset','ad'],default='ad')
    args=parser.parse_args()
    try:
        if args.command=='backup':
            print('Backup integrity=ok SHA256='+backup(args.db,args.file))
        else:
            path=Path(args.file)
            if path.stat().st_size>64*1024*1024:
                raise ValueError('Import too large for local MVP')
            text=path.read_text(encoding='utf-8-sig')
            store=Store(args.db)
            if args.command=='telegram':
                result=store.import_snapshot(json.loads(text))
            else:
                result=store.import_ads(text,currency=args.currency,account_timezone=args.account_timezone,level=args.level)
            print('Import complete: rows='+str(result['rows']))
    except (ValueError,OSError,sqlite3.Error):
        parser.exit(2,'Operation rejected; inspect schema, isolated paths and destination.\n')


if __name__=='__main__':main()
