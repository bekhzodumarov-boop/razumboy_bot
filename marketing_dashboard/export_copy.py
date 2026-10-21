"""Explicit one-way exporter. Inputs MUST be isolated copies, never a live Volume."""
import argparse
import hashlib
import hmac
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import Snapshot, SOURCES, instant


def export_copy(business, journal, *, key, stream, business_timezone='UTC'):
    if len(key)<32:
        raise ValueError('Use a stable dedicated HMAC key with at least 32 characters')
    ZoneInfo(business_timezone)
    def pseudonym(kind, value):
        return hmac.new(key.encode(), f'{stream}:{kind}:{value}'.encode(), hashlib.sha256).hexdigest()
    def connect(path):
        return closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=0.2))
    with connect(business) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        games = [{'id':r['id'],'title':r['title'][:160],'day':r['event_date'],'capacity':r['max_teams']}
                 for r in conn.execute('SELECT id,title,event_date,max_teams FROM events')]
        totals = {}
        for r in conn.execute('SELECT event_id,created_at,status,team_size FROM registrations'):
            created = datetime.fromisoformat(r[1])
            if created.tzinfo is None:
                created = created.replace(tzinfo=ZoneInfo(business_timezone))
            day = created.astimezone(ZoneInfo('Asia/Tashkent')).date().isoformat()
            row = totals.setdefault((r[0],day,r[2]),{'game':r[0],'day':day,'status':r[2],'teams':0,'players':0})
            row['teams'] += 1
            row['players'] += r[3]
        registrations = list(totals.values())
    events = []
    with connect(journal) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        columns = {r[1] for r in conn.execute('PRAGMA table_info(funnel_events)')}
        source = 'source' if 'source' in columns else "'unknown' AS source"
        for r in conn.execute(f'SELECT id,timestamp,user_id,event_id,attempt_id,event_name,step,result,dedup_key,{source} FROM funnel_events ORDER BY id'):
            events.append({'seq':r['id'],'key':pseudonym('event',r['dedup_key']), 'actor':pseudonym('actor',r['user_id']),
                           'attempt':pseudonym('attempt',r['attempt_id']) if r['attempt_id'] else None,
                           'game':r['event_id'],'at':instant(r['timestamp']).isoformat(),'name':r['event_name'],
                           'step':r['step'],'result':r['result'],'source':r['source'] if r['source'] in SOURCES else 'unknown'})
    payload = {'version':1,'stream':stream,'kind':'snapshot','generated_at':datetime.now(timezone.utc).isoformat(),
               'coverage_start':min((e['at'] for e in events),default=None), 'business_timezone':business_timezone,
               'games':games,'registrations':registrations,'events':events}
    return Snapshot.model_validate(payload).model_dump(mode='json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business-copy',required=True)
    parser.add_argument('--journal-copy',required=True)
    parser.add_argument('--stream',required=True)
    parser.add_argument('--business-timezone',default='UTC')
    parser.add_argument('--output',required=True)
    parser.add_argument('--confirm-isolated-copy',action='store_true',required=True)
    args = parser.parse_args()
    try:
        output = Path(args.output).resolve()
        if output in {Path(args.business_copy).resolve(),Path(args.journal_copy).resolve()}:
            raise ValueError('Destination conflicts with a source')
        payload = export_copy(args.business_copy,args.journal_copy,key=os.getenv('DASHBOARD_EXPORT_HMAC_KEY',''),
                              stream=args.stream,business_timezone=args.business_timezone)
        # Never overwrite an existing export by accident.
        with output.open('x',encoding='utf-8') as handle:
            json.dump(payload,handle,ensure_ascii=False)
        print('Export complete: pseudonymized events and registration aggregates only')
    except (ValueError, OSError, sqlite3.Error):
        parser.exit(2,'Export rejected; verify isolated copies, schema, key and destination.\n')


if __name__=='__main__':
    main()
