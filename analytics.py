"""Optional, privacy-limited funnel journal. Never imports config or starts the bot."""
import logging
import sqlite3
import uuid
import re
from contextlib import contextmanager, closing

logger = logging.getLogger(__name__)
EVENTS = {'bot_started', 'event_card_sent', 'registration_started',
          'registration_step_completed', 'registration_cancelled',
          'registration_completed', 'registration_failed'}
STEPS = {'start', 'card', 'team_name', 'team_size', 'captain_name', 'phone',
         'comment', 'choose_event', 'confirm'}
RESULTS = {'ok', 'cancelled', 'superseded', 'state_lost', 'handler_error',
           'unavailable', 'duplicate', 'user_missing', 'edited'}
SOURCES = {'direct', 'menu', 'telegram', 'instagram', 'qr', 'partner', 'unknown'}


def safe_source(value):
    return value if isinstance(value, str) and value in SOURCES else 'unknown'


def parse_event_link(payload):
    """Only fixed source labels are retained; never persist arbitrary payloads."""
    match = re.fullmatch(r'event_([1-9][0-9]{0,17})(?:_src_([A-Za-z0-9_-]{1,32}))?', payload or '')
    if not match:
        return None, 'unknown'
    return int(match[1]), safe_source(match[2]) if match[2] else 'direct'


class Analytics:
    def __init__(self, path):
        self.path = str(path)
        self.enabled = True
        try:
            with self.connect() as conn:
                conn.execute('''CREATE TABLE IF NOT EXISTS funnel_events (
                    id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    user_id INTEGER NOT NULL, event_id INTEGER, attempt_id TEXT,
                    event_name TEXT NOT NULL, step TEXT NOT NULL,
                    result TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE)''')
                columns = {row[1] for row in conn.execute('PRAGMA table_info(funnel_events)')}
                if 'source' not in columns:
                    conn.execute("ALTER TABLE funnel_events ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'")
                conn.execute('CREATE INDEX IF NOT EXISTS funnel_attempt ON funnel_events(attempt_id, id)')
                conn.execute('CREATE INDEX IF NOT EXISTS funnel_time ON funnel_events(timestamp)')
        except Exception:
            self.enabled = False
            logger.warning('analytics_init_failed')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=0.1)) as conn:
            with conn:
                yield conn

    def record(self, name, user_id, *, key, event_id=None, attempt_id=None,
               step='start', result='ok', source='unknown'):
        if not self.enabled:
            return
        try:
            if name not in EVENTS or step not in STEPS or result not in RESULTS:
                raise ValueError('invalid enum')
            with self.connect() as conn:
                conn.execute('''INSERT OR IGNORE INTO funnel_events
                    (user_id,event_id,attempt_id,event_name,step,result,dedup_key,source)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (int(user_id), event_id, attempt_id, name, step, result, key, safe_source(source)))
        except Exception:
            # No exceptions, input values or SQL parameters in logs.
            logger.warning('analytics_write_failed')


async def begin_attempt(state, analytics, user_id, event_id=None, delivery_key=None):
    previous = await state.get_data()
    old = previous.get('attempt_id')
    attempt = (uuid.uuid5(uuid.NAMESPACE_URL, f'razumboy:{user_id}:{delivery_key}').hex
               if delivery_key else uuid.uuid4().hex)
    if old == attempt:
        return False
    if analytics and analytics.enabled:
        try:
            with analytics.connect() as conn:
                if conn.execute('SELECT 1 FROM funnel_events WHERE dedup_key=?',
                                (f'{attempt}:start',)).fetchone():
                    return False
        except Exception:
            logger.warning('analytics_read_failed')
    if old and analytics:
        current = await state.get_state()
        old_step = current.split(':')[-1] if current and current.startswith('RegistrationState:') else 'start'
        if old_step not in STEPS:
            old_step = 'start'
        analytics.record('registration_cancelled', user_id, key=f'{old}:terminal',
                         attempt_id=old, event_id=previous.get('event_id'),
                         step=old_step, result='superseded', source=previous.get('attempt_source'))
    traffic_source = 'menu' if event_id is None else 'direct'
    if old and previous.get('event_id') == event_id:
        traffic_source = previous.get('attempt_source', traffic_source)
    elif event_id is not None and previous.get('traffic_event_id') == event_id:
        traffic_source = previous.get('traffic_source', 'direct')
    await state.clear()
    await state.update_data(attempt_id=attempt, event_id=event_id,
                            attempt_source=safe_source(traffic_source))
    if analytics:
        analytics.record('registration_started', user_id, key=f'{attempt}:start',
                         attempt_id=attempt, event_id=event_id, source=traffic_source)
    return True


def emit(analytics, name, user_id, data, step, result='ok', key=None):
    if analytics:
        attempt = data.get('attempt_id')
        analytics.record(name, user_id, attempt_id=attempt,
                         event_id=data.get('event_id'), step=step, result=result,
                         source=data.get('attempt_source'),
                         key=key or f'{attempt}:{data.get("attempt_revision", 0)}:{name}:{step}:{result}')


def report(path, *, event_id=None, date_from=None, date_to=None, source=None):
    """Read-only report; does not initialize Database or run any migrations."""
    from analytics_report import build_report
    return build_report(path, event_id=event_id, date_from=date_from,
                        date_to=date_to, source=source)


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Read-only registration funnel report (UTC)')
    parser.add_argument('database', help='Explicit analytics SQLite path')
    parser.add_argument('--event-id', type=int)
    parser.add_argument('--from', dest='date_from', help='Inclusive ISO date/aware timestamp; date = UTC midnight')
    parser.add_argument('--until', '--to', dest='date_to', help='Exclusive ISO date/aware timestamp')
    parser.add_argument('--source', choices=sorted(SOURCES))
    args = parser.parse_args()
    try:
        output = report(args.database, event_id=args.event_id, date_from=args.date_from,
                        date_to=args.date_to, source=args.source)
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(2, f'Report unavailable ({type(exc).__name__}); check filters and journal schema/path.\n')
    print(json.dumps(output, ensure_ascii=False, indent=2))
