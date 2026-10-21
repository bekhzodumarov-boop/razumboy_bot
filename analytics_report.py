"""Read-only activity report with attempt outcomes as of the exclusive cutoff."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from analytics import SOURCES, safe_source

TECHNICAL = {'handler_error', 'state_lost', 'user_missing'}
NEXT_STEP = {'start': 'team_name', 'team_name': 'team_size',
             'team_size': 'captain_name', 'captain_name': 'phone',
             'phone': 'comment', 'comment': 'choose_event', 'choose_event': 'confirm'}


def utc_boundary(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        if len(value) != 10:
            raise ValueError('Timestamp must include UTC offset')
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_report(path, *, event_id=None, date_from=None, date_to=None, source=None):
    """Metrics are events in [from,to); outcomes cover attempts active in that window.

    A form begun via menu inherits its eventual game only as of `to`. Outcomes
    use all earlier history, so a start outside the window can complete inside it.
    Future events never change the historical cutoff report.
    """
    lower, upper = utc_boundary(date_from), utc_boundary(date_to)
    if lower and upper and lower >= upper:
        raise ValueError('Empty or reversed interval')
    if event_id is not None and (type(event_id) is not int or event_id <= 0):
        raise ValueError('Invalid event ID')
    if source is not None and source not in SOURCES:
        raise ValueError('Invalid source')
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')  # One snapshot, including schema introspection.
        columns = {r[1] for r in conn.execute('PRAGMA table_info(funnel_events)')}
        projection = '*' if 'source' in columns else "*, 'unknown' AS source"
        # Stream a read-only snapshot; retain history only for attempts.
        events = []
        attempts = defaultdict(list)
        for row in conn.execute(f'SELECT {projection} FROM funnel_events ORDER BY id'):
            row = dict(row)
            timestamp = utc_boundary(row['timestamp'])
            if upper and timestamp >= upper:
                continue
            row['source'] = safe_source(row['source'])
            row['_in_window'] = not lower or timestamp >= lower
            if row['attempt_id']:
                attempts[row['attempt_id']].append(row)
            if row['_in_window']:
                events.append(row)

    effective_game = {}
    effective_source = {}
    for attempt, history in attempts.items():
        effective_game[attempt] = next((r['event_id'] for r in reversed(history)
                                        if r['event_id'] is not None), None)
        effective_source[attempt] = next((r['source'] for r in history
                                          if r['event_name'] == 'registration_started'), history[0]['source'])

    def matches(row):
        game = effective_game.get(row['attempt_id'], row['event_id'])
        label = effective_source.get(row['attempt_id'], row['source'])
        return (event_id is None or game == event_id) and (source is None or label == source)

    selected = [r for r in events if matches(r)]
    counts = Counter(r['event_name'] for r in selected)
    categories = {key: [] for key in ('unfinished', 'cancelled', 'technical_errors',
                                    'duplicates', 'superseded', 'unavailable', 'completed')}
    active = {r['attempt_id'] for r in selected if r['attempt_id']}
    for attempt in sorted(active):
        history = attempts[attempt]
        last = history[-1]
        terminals = [r for r in history if r['event_name'] in
                     {'registration_completed', 'registration_cancelled'}]
        if terminals:
            terminal = terminals[-1]
            category = ('completed' if terminal['event_name'] == 'registration_completed' else
                        'superseded' if terminal['result'] == 'superseded' else 'cancelled')
        elif last['event_name'] == 'registration_failed':
            category = ('duplicates' if last['result'] == 'duplicate' else
                        'technical_errors' if last['result'] in TECHNICAL else 'unavailable')
        else:
            category = 'unfinished'
        accepted = [r for r in history if r['event_name']=='registration_step_completed' and r['result']=='ok']
        expected = last['step'] if last['event_name']=='registration_failed' else NEXT_STEP.get(last['step'])
        if last['result'] == 'edited':
            expected = 'team_name'
        elif last['step'] == 'comment' and effective_game[attempt] is not None:
            expected = 'confirm'
        categories[category].append({
            'attempt_id': attempt, 'user_id': last['user_id'],
            'event_id': effective_game[attempt], 'source': effective_source[attempt],
            'step': last['step'], 'event_name': last['event_name'],
            'result': last['result'], 'timestamp': last['timestamp'],
            'last_completed_step': accepted[-1]['step'] if accepted else None,
            'expected_step': expected if category != 'completed' else None})

    steps = defaultdict(set)
    step_events = Counter()
    for row in selected:
        if row['event_name']=='registration_step_completed' and row['result']=='ok':
            steps[row['step']].add(row['attempt_id'])
            step_events[row['step']] += 1
    breakdown = defaultdict(Counter)
    for row in selected:
        breakdown[effective_source.get(row['attempt_id'], row['source'])][row['event_name']] += 1
    failures = [r for r in selected if r['event_name']=='registration_failed']
    unlinked_failures = [{k: r[k] for k in ('user_id','event_id','step','result','timestamp','source')}
                        for r in failures if not r['attempt_id']]
    return {
        'filters': {'event_id': event_id, 'from_inclusive': lower.isoformat() if lower else None,
                    'until_exclusive': upper.isoformat() if upper else None, 'source': source},
        'bot_starts': counts['bot_started'],
        'unique_starters': len({r['user_id'] for r in selected if r['event_name']=='bot_started'}),
        'event_cards_sent': counts['event_card_sent'],
        'registrations_started': counts['registration_started'],
        'registrations_completed': counts['registration_completed'],
        'steps': {step: len(ids) for step, ids in sorted(steps.items())},
        'step_events': dict(sorted(step_events.items())),
        'outcome_counts': {k: len(v) for k,v in categories.items()},
        **categories,
        'technical_error_events': sum(r['result'] in TECHNICAL for r in failures),
        'duplicate_events': sum(r['result']=='duplicate' for r in failures),
        'unlinked_failures': unlinked_failures,
        'by_source': {k: dict(v) for k,v in sorted(breakdown.items())}}
