"""Additive delivery state and aggregate metrics, independent of subscription."""
from contextlib import closing
import json


class DeliveryStore:
    def _init_delivery(self):
        with closing(self._connect()) as conn, conn:
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS user_delivery_state (
                telegram_id INTEGER PRIMARY KEY,
                availability TEXT NOT NULL DEFAULT 'unknown'
                  CHECK(availability IN ('unknown','reachable','blocked')),
                last_successful_send_at TEXT,
                revision INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS delivery_counters (
                day TEXT NOT NULL, result TEXT NOT NULL, count INTEGER NOT NULL,
                PRIMARY KEY(day,result));
              CREATE TABLE IF NOT EXISTS delivery_runs (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                kind TEXT NOT NULL, metrics TEXT NOT NULL);
            ''')

    def get_delivery_state(self, telegram_id):
        with closing(self._connect()) as conn:
            row = conn.execute('SELECT * FROM user_delivery_state WHERE telegram_id=?', (telegram_id,)).fetchone()
            return dict(row) if row else dict(availability='unknown', last_successful_send_at=None, revision=0)

    def restore_availability(self, telegram_id):
        with closing(self._connect()) as conn, conn:
            conn.execute('''INSERT INTO user_delivery_state(telegram_id,availability,revision) VALUES (?,'reachable',1)
              ON CONFLICT(telegram_id) DO UPDATE SET availability='reachable',revision=revision+1''', (telegram_id,))

    def mark_delivery_blocked(self, telegram_id, revision=None):
        with closing(self._connect()) as conn, conn:
            conn.execute('INSERT OR IGNORE INTO user_delivery_state(telegram_id) VALUES (?)', (telegram_id,))
            if revision is None:  # Authoritative private my_chat_member event.
                conn.execute("UPDATE user_delivery_state SET availability='blocked',revision=revision+1 WHERE telegram_id=?", (telegram_id,))
            else:  # Do not overwrite a newer /start or unblock event.
                conn.execute("UPDATE user_delivery_state SET availability='blocked' WHERE telegram_id=? AND revision=?", (telegram_id,revision))

    def mark_delivery_success(self, telegram_id):
        with closing(self._connect()) as conn, conn:
            conn.execute('INSERT OR IGNORE INTO user_delivery_state(telegram_id) VALUES (?)', (telegram_id,))
            conn.execute('''UPDATE user_delivery_state SET last_successful_send_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                availability=CASE WHEN availability='blocked' THEN 'blocked' ELSE 'reachable' END
                WHERE telegram_id=?''', (telegram_id,))

    def count_delivery_result(self, result):
        with closing(self._connect()) as conn, conn:
            conn.execute('''INSERT INTO delivery_counters(day,result,count) VALUES(date('now'),?,1)
                ON CONFLICT(day,result) DO UPDATE SET count=count+1''', (result,))

    def save_delivery_run(self, kind, metrics):
        with closing(self._connect()) as conn, conn:
            conn.execute('INSERT INTO delivery_runs(kind,metrics) VALUES (?,?)', (kind,json.dumps(metrics)))

    def get_delivery_report(self):
        with closing(self._connect()) as conn:
            states = {row[0]:row[1] for row in conn.execute('''SELECT COALESCE(d.availability,'unknown'),COUNT(*)
                FROM users u LEFT JOIN user_delivery_state d USING(telegram_id) GROUP BY 1''')}
            subscribers = conn.execute('''SELECT COUNT(*) FROM users u WHERE subscribed=1
                AND NOT EXISTS(SELECT 1 FROM user_delivery_state d WHERE d.telegram_id=u.telegram_id AND availability='blocked')''').fetchone()[0]
            counters = {row[0]:row[1] for row in conn.execute('SELECT result,SUM(count) FROM delivery_counters GROUP BY result')}
            runs = [dict(kind=row[0],created_at=row[1],**json.loads(row[2])) for row in conn.execute(
                'SELECT kind,created_at,metrics FROM delivery_runs ORDER BY id DESC LIMIT 5')]
            external = conn.execute('''SELECT COUNT(*) FROM user_delivery_state d WHERE NOT EXISTS
                (SELECT 1 FROM users u WHERE u.telegram_id=d.telegram_id)''').fetchone()[0]
        return dict(availability={key:states.get(key,0) for key in ('unknown','reachable','blocked')},
                    eligible_subscribers=subscribers, other_private_contacts=external,
                    api_attempts=sum(value for key,value in counters.items() if key!='skipped_blocked'),
                    api_results=counters, recent_runs=runs)
