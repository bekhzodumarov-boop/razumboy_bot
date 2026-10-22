"""Export an aggregate dashboard snapshot without opening or modifying the bot.

Only SELECTs on a mode=ro transaction. Registration confirmation is never attendance.
No users, phones, captains, Telegram IDs, comments or attempt-level rows are exported.
"""
import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys


def iso_date(value):
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f'Unsupported event date: {value!r}')


def snapshot(db_path, *, date_from=None, date_to=None, analytics_path=None):
    lower = date.fromisoformat(date_from) if date_from else None
    upper = date.fromisoformat(date_to) if date_to else None
    if lower and upper and lower > upper:
        raise ValueError('Reversed date interval')
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    events = []
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        for e in conn.execute('SELECT id, title, event_date FROM events ORDER BY id'):
            day = iso_date(e['event_date'])
            parsed = date.fromisoformat(day)
            if (lower and parsed < lower) or (upper and parsed > upper):
                continue
            rows = conn.execute('SELECT team_name, team_size, status FROM registrations WHERE event_id=? ORDER BY id', (e['id'],)).fetchall()
            teams = []
            cancelled = 0
            for r in rows:
                if r['status'] == 'cancelled':
                    cancelled += 1
                    continue
                if r['status'] != 'confirmed':
                    continue
                if not isinstance(r['team_size'], int) or not 1 <= r['team_size'] <= 1000:
                    raise ValueError('Invalid registration group size')
                teams.append({'name': r['team_name'], 'size': r['team_size'], 'kind': 'team'})
            events.append({'id': 'bot-'+str(e['id']), 'date': day, 'title': e['title'],
                           'format': 'Не классифицирован', 'source': 'Снимок регистраций бота; явка не установлена',
                           'attended': None, 'teams': teams, 'cancelled': cancelled, 'funnel': None})
    # Existing analytics_report handles attempt history correctly. Only allowlisted aggregates leave this process.
    if analytics_path:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from analytics_report import build_report
        for event in events:
            r = build_report(analytics_path, event_id=int(event['id'][4:]))
            event['funnel'] = {k: r[k] for k in ('bot_starts', 'registrations_started', 'registrations_completed')}
    return {'schema_version': 1, 'as_of': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source_label': 'Экспорт SQLite только для чтения; явка и оплата не подтверждены',
            'events': events, 'competitors': []}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', required=True)
    ap.add_argument('--from', dest='date_from')
    ap.add_argument('--to', dest='date_to')
    ap.add_argument('--analytics')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    output = Path(args.out).resolve()
    for source in (args.db, args.analytics):
        if source and output == Path(source).resolve():
            ap.error('Output cannot overwrite an input database')
    try:
        result = snapshot(args.db, date_from=args.date_from, date_to=args.date_to, analytics_path=args.analytics)
        # Exclusive creation protects existing reports and unrelated files.
        with output.open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write('\n')
    except (sqlite3.Error, ValueError, OSError) as exc:
        ap.exit(1, f'Export failed: {exc}\n')
    print(f'Exported {len(result["events"])} events. Attendance remains unknown.')


if __name__ == '__main__':
    main()
