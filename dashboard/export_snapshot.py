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

METHODS = ('uzum', 'payme', 'click', 'card', 'cash')


def finance_snapshot(conn, event_id, registered):
    """Only allowlisted business data; never instantiate the writing FinanceStore."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'finance_games', 'finance_teams', 'finance_payments', 'finance_expenses'} <= tables:
        return None
    setting = conn.execute('SELECT ticket_uzs FROM finance_games WHERE event_id=?', (event_id,)).fetchone()
    if setting is None:
        return None
    teams = []
    for t in conn.execute('''SELECT t.id,t.name,t.actual_players,t.registration_id,r.status
                            FROM finance_teams t LEFT JOIN registrations r ON r.id=t.registration_id
                            WHERE t.event_id=? ORDER BY t.id''', (event_id,)):
        payments = {m: {'players': 0, 'amount_uzs': 0} for m in METHODS}
        for p in conn.execute('SELECT method,players,amount_uzs FROM finance_payments WHERE team_id=?', (t['id'],)):
            payments[p['method']] = {'players': p['players'], 'amount_uzs': p['amount_uzs']}
        # Cancelled bookings with no attendance/payment are not pending arrivals.
        if t['status'] == 'cancelled' and t['actual_players'] is None and not any(p['players'] or p['amount_uzs'] for p in payments.values()):
            continue
        teams.append({'id': str(t['id']), 'registration_id': t['registration_id'], 'name': t['name'],
                      'actual_players': t['actual_players'], 'payments': payments})
    linked = {t['registration_id'] for t in teams if t['registration_id'] is not None}
    missing = sum(r['id'] not in linked for r in registered if r['status'] == 'confirmed')
    by_method = {m: {'players': sum(t['payments'][m]['players'] for t in teams),
                     'amount_uzs': sum(t['payments'][m]['amount_uzs'] for t in teams)} for m in METHODS}
    expenses = [dict(r) for r in conn.execute('''SELECT title,kind,amount_uzs,status FROM finance_expenses
                        WHERE event_id=? ORDER BY id''', (event_id,))]
    income = sum(v['amount_uzs'] for v in by_method.values())
    costs = sum(x['amount_uzs'] for x in expenses if x['status'] == 'confirmed' and x['kind'] == 'cost')
    distributions = sum(x['amount_uzs'] for x in expenses if x['status'] == 'confirmed' and x['kind'] == 'distribution')
    return {'ticket_uzs': setting['ticket_uzs'], 'teams': teams, 'by_method': by_method, 'expenses': expenses,
            'actual_players': sum(t['actual_players'] or 0 for t in teams),
            'arrived_teams': sum(t['actual_players'] is not None and t['actual_players'] > 0 for t in teams),
            'unknown_teams': missing + sum(t['actual_players'] is None for t in teams),
            'paid_players': sum(v['players'] for v in by_method.values()),
            'income_uzs': income, 'costs_uzs': costs, 'distributions_uzs': distributions,
            'result_uzs': income-costs, 'balance_uzs': income-costs-distributions,
            'pending_expenses': sum(x['status'] == 'pending' for x in expenses)}


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
    source_keys = {}
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        for e in conn.execute('SELECT id, title, event_date FROM events ORDER BY id'):
            day = iso_date(e['event_date'])
            parsed = date.fromisoformat(day)
            if (lower and parsed < lower) or (upper and parsed > upper):
                continue
            rows = conn.execute('SELECT id, team_name, team_size, status FROM registrations WHERE event_id=? ORDER BY id', (e['id'],)).fetchall()
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
                teams.append({'id': str(r['id']), 'name': r['team_name'], 'size': r['team_size'], 'kind': 'team'})
            finance = finance_snapshot(conn, e['id'], rows)
            reg_columns = {r[1] for r in conn.execute('PRAGMA table_info(registrations)')}
            user_columns = {r[1] for r in conn.execute('PRAGMA table_info(users)')}
            if {'user_id','created_at'} <= reg_columns and {'id','telegram_id'} <= user_columns:
                source_keys[e['id']] = {str(r['id']): (r['telegram_id'],r['created_at']) for r in conn.execute(
                    '''SELECT r.id,u.telegram_id,r.created_at FROM registrations r JOIN users u ON u.id=r.user_id
                       WHERE r.event_id=? AND r.status='confirmed' ''',(e['id'],))}
            events.append({'id': 'bot-'+str(e['id']), 'date': day, 'title': e['title'],
                           'format': 'Стреляй и пой' if 'СТРЕЛЯЙ' in e['title'].upper() else 'Разумбой',
                           'source': 'Telegram-бот; заявки, ручная явка и учет оплат',
                           'attended': None, 'teams': teams, 'cancelled': cancelled, 'funnel': None,
                           'finance': finance, 'sources': None})
    # Existing analytics_report handles attempt history correctly. Only allowlisted aggregates leave this process.
    if analytics_path:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from analytics_report import build_report
        for event in events:
            try:
                r = build_report(analytics_path, event_id=int(event['id'][4:]))
                event['funnel'] = {k: r[k] for k in ('bot_starts', 'registrations_started', 'registrations_completed')}
                event['sources'] = {label: {k: counts.get(k, 0) for k in
                    ('bot_started', 'event_card_sent', 'registration_started', 'registration_completed')}
                    for label, counts in r['by_source'].items()}
                # Exact user + game + near registration time. Never use an old
                # attempt's label for a later booking, and never export user IDs.
                keys = source_keys.get(int(event['id'][4:]), {})
                for team in event['teams']:
                    team['source'] = None
                    if team['id'] not in keys:
                        continue
                    uid,created = keys[team['id']]
                    try:
                        booking_time = datetime.fromisoformat(created.replace('Z','+00:00'))
                        if booking_time.tzinfo is None:
                            booking_time=booking_time.replace(tzinfo=timezone.utc)
                        matches=[a for a in r['completed'] if a['user_id']==uid and abs((datetime.fromisoformat(a['timestamp'].replace('Z','+00:00'))-booking_time).total_seconds())<=300]
                        if len(matches)==1:
                            team['source']=matches[0]['source']
                    except (TypeError,ValueError):
                        pass
            except (OSError, sqlite3.Error, ValueError, KeyError):
                pass  # Missing analytics never hides registrations or becomes zero conversions.
    return {'schema_version': 1, 'as_of': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source_label': 'Живые данные Telegram; весь доступный период; оплаты введены администраторами',
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
