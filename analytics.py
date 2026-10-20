"""Optional, privacy-limited funnel journal. Never imports config or starts the bot."""
import logging
import sqlite3
import uuid
from contextlib import contextmanager, closing
from pathlib import Path

logger = logging.getLogger(__name__)
EVENTS = {'bot_started', 'event_card_sent', 'registration_started',
          'registration_step_completed', 'registration_cancelled',
          'registration_completed', 'registration_failed'}
STEPS = {'start', 'card', 'team_name', 'team_size', 'captain_name', 'phone',
         'comment', 'choose_event', 'confirm'}
RESULTS = {'ok', 'cancelled', 'superseded', 'state_lost', 'handler_error',
           'unavailable', 'duplicate', 'user_missing', 'edited'}


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
                conn.execute('CREATE INDEX IF NOT EXISTS funnel_attempt ON funnel_events(attempt_id, id)')
        except Exception:
            self.enabled = False
            logger.warning('analytics_init_failed')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=0.1)) as conn:
            with conn:
                yield conn

    def record(self, name, user_id, *, key, event_id=None, attempt_id=None,
               step='start', result='ok'):
        if not self.enabled:
            return
        try:
            if name not in EVENTS or step not in STEPS or result not in RESULTS:
                raise ValueError('invalid enum')
            with self.connect() as conn:
                conn.execute('''INSERT OR IGNORE INTO funnel_events
                    (user_id,event_id,attempt_id,event_name,step,result,dedup_key)
                    VALUES (?,?,?,?,?,?,?)''',
                    (int(user_id), event_id, attempt_id, name, step, result, key))
        except Exception:
            # No exceptions, input values or SQL parameters in logs.
            logger.warning('analytics_write_failed')


async def begin_attempt(state, analytics, user_id, event_id=None, source=None):
    previous = await state.get_data()
    old = previous.get('attempt_id')
    attempt = uuid.uuid5(uuid.NAMESPACE_URL, f'razumboy:{user_id}:{source}').hex if source else uuid.uuid4().hex
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
        analytics.record('registration_cancelled', user_id, key=f'{old}:terminal',
                         attempt_id=old, event_id=previous.get('event_id'),
                         step='start', result='superseded')
    await state.clear()
    await state.update_data(attempt_id=attempt, event_id=event_id)
    if analytics:
        analytics.record('registration_started', user_id, key=f'{attempt}:start',
                         attempt_id=attempt, event_id=event_id)
    return True


def emit(analytics, name, user_id, data, step, result='ok', key=None):
    if analytics:
        attempt = data.get('attempt_id')
        analytics.record(name, user_id, attempt_id=attempt,
                         event_id=data.get('event_id'), step=step, result=result,
                         key=key or f'{attempt}:{data.get("attempt_revision", 0)}:{name}:{step}:{result}')


def report(path):
    """Read-only report; does not initialize Database or run any migrations."""
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        counts = {r['event_name']: r['n'] for r in conn.execute(
            'SELECT event_name, COUNT(*) n FROM funnel_events GROUP BY event_name')}
        unfinished = [dict(r) for r in conn.execute('''
            SELECT f.attempt_id, f.user_id,
              (SELECT event_id FROM funnel_events WHERE attempt_id=f.attempt_id
               AND event_id IS NOT NULL ORDER BY id DESC LIMIT 1) event_id,
              f.step, f.event_name, f.result, f.timestamp
            FROM funnel_events f
            WHERE f.attempt_id IS NOT NULL
              AND f.id=(SELECT MAX(id) FROM funnel_events WHERE attempt_id=f.attempt_id)
              AND NOT EXISTS (SELECT 1 FROM funnel_events t
                WHERE t.attempt_id=f.attempt_id AND t.event_name IN
                ('registration_completed','registration_cancelled'))
            ORDER BY f.id''')]
        unique = conn.execute("SELECT COUNT(DISTINCT user_id) FROM funnel_events WHERE event_name='bot_started'").fetchone()[0]
    return {'bot_starts': counts.get('bot_started', 0), 'unique_starters': unique,
            'registrations_started': counts.get('registration_started', 0),
            'registrations_completed': counts.get('registration_completed', 0),
            'unfinished': unfinished}


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Read-only registration funnel report (UTC)')
    parser.add_argument('database', help='Explicit analytics SQLite path')
    print(json.dumps(report(parser.parse_args().database), ensure_ascii=False, indent=2))
