"""Independent analytics store, validated imports and aggregate-only queries."""
import csv
import hashlib
import io
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCES = {'direct', 'menu', 'telegram', 'instagram', 'qr', 'partner', 'unknown'}
NAMES = {'bot_started', 'event_card_sent', 'registration_started', 'registration_completed',
         'registration_step_completed', 'registration_failed', 'registration_cancelled'}
STEPS = {'start', 'card', 'team_name', 'team_size', 'captain_name', 'phone', 'comment', 'choose_event', 'confirm'}
RESULTS = {'ok', 'cancelled', 'superseded', 'state_lost', 'handler_error', 'unavailable', 'duplicate', 'user_missing', 'edited'}


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return parsed.astimezone(timezone.utc)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Event(Strict):
    seq: int = Field(ge=0)
    key: str = Field(pattern=r'^[a-f0-9]{64}$')
    actor: str = Field(pattern=r'^[a-f0-9]{64}$')
    attempt: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    game: int | None = Field(default=None, ge=1, le=2**63-1)
    at: str
    name: str
    step: str
    result: str
    source: str

    @field_validator('at')
    @classmethod
    def timestamp(cls, value):
        return instant(value).isoformat()

    @field_validator('name', 'step', 'result', 'source')
    @classmethod
    def enum(cls, value, info):
        allowed = {'name': NAMES, 'step': STEPS, 'result': RESULTS, 'source': SOURCES}
        if value not in allowed[info.field_name]:
            raise ValueError('Unsupported event enum')
        return value


class Game(Strict):
    id: int = Field(ge=1)
    title: str = Field(max_length=160)
    day: date
    capacity: int | None = Field(default=None, ge=0)


class Registrations(Strict):
    game: int = Field(ge=1)
    day: date
    status: Literal['confirmed', 'cancelled']
    teams: int = Field(ge=0)
    players: int = Field(ge=0)


class Snapshot(Strict):
    version: Literal[1] = 1
    stream: str = Field(pattern=r'^[a-z0-9-]{1,64}$')
    kind: Literal['demo', 'snapshot']
    generated_at: str
    coverage_start: str | None = None
    business_timezone: str = 'UTC'
    games: list[Game] = Field(max_length=5000)
    registrations: list[Registrations] = Field(max_length=50000)
    events: list[Event] = Field(max_length=100000)

    @field_validator('generated_at', 'coverage_start')
    @classmethod
    def timestamp(cls, value):
        return instant(value).isoformat() if value else None

    @field_validator('business_timezone')
    @classmethod
    def zone(cls, value):
        ZoneInfo(value)
        return value


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ads(natural_key TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY,at TEXT NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL,rows INTEGER NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=2)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def snapshot(self):
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM snapshot WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def import_snapshot(self, payload):
        item = Snapshot.model_validate(payload).model_dump(mode='json')
        keys = [e['key'] for e in item['events']]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate event keys')
        games = {g['id'] for g in item['games']}
        if len(games) != len(item['games']) or any(r['game'] not in games for r in item['registrations']):
            raise ValueError('Invalid game references')
        if any(instant(e['at']) > instant(item['generated_at']) for e in item['events']):
            raise ValueError('Future events in snapshot')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT payload FROM snapshot WHERE id=1').fetchone()
            if previous:
                old = json.loads(previous[0])
                if (old['stream'], old['kind'], old['business_timezone']) != (item['stream'], item['kind'], item['business_timezone']):
                    raise ValueError('Use a separate database for a different stream')
                existing = {e['key']: e for e in item['events']}
                if instant(item['generated_at']) < instant(old['generated_at']) or any(existing.get(e['key']) != e for e in old['events']):
                    raise ValueError('Snapshot would lose or rewrite event history')
                if sum(r['teams'] for r in item['registrations']) < sum(r['teams'] for r in old['registrations']):
                    raise ValueError('Snapshot would lose registrations')
            packed = json.dumps(item, sort_keys=True)
            conn.execute('INSERT INTO snapshot VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (packed,))
            self._log(conn, 'telegram', hashlib.sha256(packed.encode()).hexdigest(), len(keys))
        return {'rows': len(keys), 'kind': item['kind']}

    def _log(self, conn, kind, digest, rows):
        conn.execute('INSERT INTO imports(at,kind,digest,rows) VALUES(?,?,?,?)',
                     (datetime.now(timezone.utc).isoformat(), kind, digest, rows))

    def import_ads(self, text, *, currency, account_timezone, level):
        rows = parse_ads(text, currency, account_timezone, level)
        with self.connect() as conn:
            for row in rows:
                key = json.dumps([row[k] for k in ('account_id', 'currency', 'timezone', 'level', 'day', 'campaign_id', 'adset_id', 'ad_id')])
                conn.execute('INSERT INTO ads VALUES(?,?) ON CONFLICT(natural_key) DO UPDATE SET payload=excluded.payload',
                             (key, json.dumps(row)))
            self._log(conn, 'meta_csv', hashlib.sha256(text.encode()).hexdigest(), len(rows))
        return {'rows': len(rows), 'updated_at': datetime.now(timezone.utc).isoformat()}

    def query(self, start, until, game=None, source=None, campaign=None, creative=None,
              first_from=None, currency='UZS', account_timezone='Asia/Tashkent', level='ad'):
        lower, upper = date.fromisoformat(start), date.fromisoformat(until)
        if lower >= upper or (upper-lower).days > 366:
            raise ValueError('Use an exclusive end date and a window of up to 366 days')
        if source and source not in SOURCES:
            raise ValueError('Unsupported source')
        if level not in {'campaign', 'adset', 'ad'} or currency not in {'UZS', 'USD', 'EUR'}:
            raise ValueError('Unsupported reporting dimension')
        tz = ZoneInfo('Asia/Tashkent')
        ZoneInfo(account_timezone)
        cutoff = datetime.combine(upper, time(), tz).astimezone(timezone.utc)
        floor = datetime.combine(lower, time(), tz).astimezone(timezone.utc)
        first_floor = date.fromisoformat(first_from) if first_from else None
        snapshot = self.snapshot()
        all_events = [e for e in (snapshot or {}).get('events', []) if instant(e['at']) < cutoff]
        attempts = defaultdict(list)
        first = {}
        for event in sorted(all_events, key=lambda e: (instant(e['at']), e['seq'], e['key'])):
            actor = event['actor']
            first[actor] = min(first.get(actor, event['at']), event['at'])
            if event['attempt']:
                attempts[event['attempt']].append(event)
        assignment = {key: next((e['game'] for e in reversed(history) if e['game'] is not None), None)
                      for key, history in attempts.items()}
        attribution = {key: next((e['source'] for e in history if e['name']=='registration_started'), history[0]['source'])
                       for key, history in attempts.items()}
        selected = []
        # Campaign/ad attribution does not exist in the Telegram source schema.
        telegram_available = bool(snapshot) and not campaign and not creative
        for event in all_events if telegram_available else []:
            if instant(event['at']) < floor:
                continue
            if game and assignment.get(event['attempt'], event['game']) != game:
                continue
            if source and attribution.get(event['attempt'], event['source']) != source:
                continue
            if first_floor and instant(first[event['actor']]).astimezone(tz).date() < first_floor:
                continue
            selected.append(event)
        counts = Counter(e['name'] for e in selected)
        stages = []
        for name, label in [('bot_started', 'Запуски бота'), ('event_card_sent', 'Карточки игры'),
                            ('registration_started', 'Начала регистрации'), ('registration_completed', 'Завершения')]:
            stages.append({'key': name, 'label': label, 'events': counts[name] if telegram_available else None,
                           'unique': len({e['actor'] for e in selected if e['name']==name}) if telegram_available else None})
        outcomes = Counter()
        dropoffs = Counter()
        for key in {e['attempt'] for e in selected if e['attempt']}:
            history = attempts[key]
            last = history[-1]
            terminal = [e for e in history if e['name'] in {'registration_completed', 'registration_cancelled'}]
            if terminal:
                e = terminal[-1]
                state = 'completed' if e['name']=='registration_completed' else 'superseded' if e['result']=='superseded' else 'cancelled'
            elif last['name']=='registration_failed':
                state = 'duplicates' if last['result']=='duplicate' else 'technical_errors' if last['result'] in {'handler_error','state_lost','user_missing'} else 'unavailable'
            else:
                state = 'unfinished'
                dropoffs[last['step']] += 1
            outcomes[state] += 1
        with self.connect() as conn:
            ads = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM ads')]
            updates = [{'at': r[0], 'kind': r[1], 'rows': r[2]} for r in conn.execute('SELECT at,kind,rows FROM imports ORDER BY id DESC LIMIT 20')]
        ad_options = [a for a in ads if a['currency']==currency and a['timezone']==account_timezone and a['level']==level]
        ads = [a for a in ads if start <= a['day'] < until and a['currency']==currency and
               a['timezone']==account_timezone and a['level']==level and
               (not campaign or a['campaign_id']==campaign) and (not creative or a['ad_id']==creative)]
        # No reliable assignment of Meta rows to game, source or actor-first-date.
        ads_available = bool(ads) and not game and not source and not first_from
        grouped = defaultdict(list)
        for row in ads if ads_available else []:
            grouped[(row['campaign_id'], row['adset_id'], row['ad_id'])].append(row)
        campaigns = []
        for _, group in grouped.items():
            row = group[-1]
            campaigns.append({**{k: row[k] for k in ('campaign_id','campaign_name','adset_id','adset_name','ad_id','ad_name')},
                              **ad_metrics(group), 'bot_starts': None, 'registrations': None, 'cpl': None, 'players': None})
        business_available = bool(snapshot) and not source and not campaign and not creative and not first_from
        registrations = [r for r in (snapshot or {}).get('registrations', []) if start <= r['day'] < until and (not game or r['game']==game)]
        confirmed = [r for r in registrations if r['status']=='confirmed']
        teams = sum(r['teams'] for r in confirmed) if business_available else None
        players = sum(r['players'] for r in confirmed) if business_available else None
        games = []
        for g in (snapshot or {}).get('games', []):
            if game and g['id'] != game:
                continue
            regs = [r for r in confirmed if r['game']==g['id']]
            n = sum(r['teams'] for r in regs)
            p = sum(r['players'] for r in regs)
            games.append({**g, 'weekday': date.fromisoformat(g['day']).weekday(), 'teams': n if business_available else None,
                          'players': p if business_available else None, 'average_size': round(p/n,2) if n and business_available else None,
                          'new_teams': None, 'returning_teams': None, 'minimum_fill': None, 'spend': None,
                          'booking_curve': [{'day': r['day'], 'days_before': (date.fromisoformat(g['day'])-date.fromisoformat(r['day'])).days,
                                             'teams': r['teams']} for r in regs] if business_available else []})
        daily_events, daily_ads = defaultdict(Counter), defaultdict(list)
        for e in selected:
            daily_events[instant(e['at']).astimezone(tz).date().isoformat()][e['name']] += 1
        if ads_available:
            for row in ads:
                daily_ads[row['day']].append(row)
        timeline = []
        for offset in range((upper-lower).days):
            day = (lower+timedelta(days=offset)).isoformat()
            day_events = daily_events[day]
            day_ads = daily_ads[day]
            timeline.append({'day': day, 'started': day_events['registration_started'] if telegram_available else None,
                             'completed': day_events['registration_completed'] if telegram_available else None,
                             'spend': ad_metrics(day_ads)['spend'] if day_ads else None})
        by_source = []
        for label in sorted(SOURCES | {'facebook'}):
            rows = [e for e in selected if attribution.get(e['attempt'], e['source'])==label]
            known = telegram_available and label in SOURCES
            by_source.append({'source': label, 'starts': sum(e['name']=='bot_started' for e in rows) if known else None,
                              'registrations': sum(e['name']=='registration_completed' for e in rows) if known else None,
                              'attempts': sum(e['name']=='registration_started' for e in rows) if known else None})
        return {'options': {'games': (snapshot or {}).get('games', []),
                            'campaigns': list({(a['campaign_id'],a['ad_id']): {k:a[k] for k in ('campaign_id','campaign_name','ad_id','ad_name')} for a in ad_options}.values())},
                'meta': {'kind': (snapshot or {}).get('kind', 'empty'), 'generated_at': (snapshot or {}).get('generated_at'),
                          'coverage_start': (snapshot or {}).get('coverage_start'), 'timezone': 'Asia/Tashkent',
                          'business_timezone': (snapshot or {}).get('business_timezone'), 'until_exclusive': until,
                          'updates': updates},
                'stages': stages, 'outcomes': dict(outcomes) if telegram_available else None, 'dropoffs': dict(dropoffs),
                'metrics': {**ad_metrics(ads if ads_available else []), 'teams': teams, 'players': players,
                            'cancelled_bookings': sum(r['teams'] for r in registrations if r['status']=='cancelled') if business_available else None,
                            'unique_users': len({e['actor'] for e in selected}) if telegram_available else None,
                            'cpl': None, 'cost_per_player': None, 'cac': None, 'roas': None, 'romi': None},
                'campaigns': campaigns, 'games': games, 'sources': by_source, 'timeline': timeline,
                'notes': ['Соотношения событий за период — не точная пользовательская когорта.',
                          'Meta CSV: даты в часовом поясе аккаунта; Telegram — Ташкент. Охват не суммируется.',
                          'Заявки: текущие статусы на дату снимка; дата создания приведена к Ташкенту экспортёром.',
                          'Кампания/креатив/игра не связаны с расходами или игроками: соответствующие KPI — Нет данных.',
                          'Первая дата взаимодействия — только первая наблюдаемая в доступной истории.']}


def ad_metrics(rows):
    if not rows:
        return {k: None for k in ('spend','impressions','clicks','link_clicks','reach','frequency','cpm','ctr','cpc')}
    spend = sum(Decimal(r['spend']) for r in rows)
    impressions = sum(r['impressions'] for r in rows)
    def complete_sum(key):
        return sum(r[key] for r in rows) if all(r[key] is not None for r in rows) else None
    clicks, links = complete_sum('clicks'), complete_sum('link_clicks')
    reach = rows[0]['reach'] if len(rows)==1 else None
    return {'spend': float(spend), 'impressions': impressions, 'clicks': clicks, 'link_clicks': links, 'reach': reach,
            'frequency': round(impressions/reach, 3) if reach else None,
            'cpm': float(spend*1000/impressions) if impressions else None,
            'ctr': round(links*100/impressions,3) if links is not None and impressions else None,
            'cpc': float(spend/links) if links else None}


ALIASES = {'Account ID':'account_id','Campaign ID':'campaign_id','Campaign name':'campaign_name',
           'Ad set ID':'adset_id','Ad set name':'adset_name','Ad ID':'ad_id','Ad name':'ad_name',
           'Reporting starts':'date_start','Reporting ends':'date_stop','Impressions':'impressions',
           'Reach':'reach','Clicks (all)':'clicks','Link clicks':'link_clicks', 'Amount spent':'spend',
           'Начало отчетности':'date_start','Конец отчетности':'date_stop','Показы':'impressions',
           'Охват':'reach','Клики по ссылке':'link_clicks','Название кампании':'campaign_name'}
CSV_COLUMNS = ['account_id','date_start','date_stop','campaign_id','campaign_name','adset_id','adset_name','ad_id','ad_name','spend','impressions','reach','clicks','link_clicks']


def parse_ads(text, currency, account_timezone, level):
    if currency not in {'UZS','USD','EUR'} or level not in {'campaign','adset','ad'}:
        raise ValueError('Unsupported currency or granularity')
    ZoneInfo(account_timezone)
    if len(text.encode()) > 1024*1024:
        raise ValueError('CSV limit: 1 MiB')
    text = text.lstrip('\ufeff')
    first = text.splitlines()[0] if text else ''
    delimiter = ';' if first.count(';') > first.count(',') else '\t' if '\t' in first else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    mapped = [ALIASES.get(h, 'spend' if h==f'Amount spent ({currency})' else h) for h in headers]
    required = {'account_id','date_start','date_stop','campaign_id','campaign_name','spend','impressions'}
    if level in {'adset','ad'}:
        required |= {'adset_id','adset_name'}
    if level=='ad':
        required |= {'ad_id','ad_name'}
    if len(mapped)!=len(set(mapped)) or not required.issubset(mapped) or not set(mapped).issubset(CSV_COLUMNS):
        raise ValueError('CSV columns do not match the documented schema/template')
    rows, keys = [], set()
    for n, original in enumerate(reader, start=2):
        if n>10002 or None in original or any(v is None or len(v)>4096 for v in original.values()):
            raise ValueError('Invalid CSV row or row limit')
        raw = dict(zip(mapped, original.values()))
        day = date.fromisoformat(raw['date_start'])
        if day.isoformat()!=raw['date_start'] or raw['date_stop'] != raw['date_start']:
            raise ValueError('Only daily rows (date_start=date_stop) are accepted')
        def count(key, required=False):
            value = raw.get(key,'').strip()
            if not value and not required:
                return None
            if not value.isascii() or not value.isdigit() or len(value)>15:
                raise ValueError('Invalid nonnegative integer')
            return int(value)
        try:
            spend = Decimal(raw['spend'].replace(' ','').replace('\u00a0','').replace(',','.'))
        except InvalidOperation:
            raise ValueError('Invalid decimal amount') from None
        if not spend.is_finite() or spend<0 or spend>Decimal('1000000000000') or spend.as_tuple().exponent < -2:
            raise ValueError('Use nonnegative amounts with at most two decimal places')
        row = {'day':day.isoformat(),'currency':currency,'timezone':account_timezone,'level':level,'spend':str(spend),
               'impressions':count('impressions',True),'reach':count('reach'),'clicks':count('clicks'),'link_clicks':count('link_clicks')}
        for key in ('account_id','campaign_id','adset_id','ad_id'):
            value = raw.get(key,'').strip()
            must = key in required
            if value and (not value.isascii() or not value.isdigit() or len(value)>32) or must and not value:
                raise ValueError('IDs must be original decimal strings, not Excel scientific notation')
            if key=='ad_id' and level!='ad' and value or key=='adset_id' and level=='campaign' and value:
                raise ValueError('IDs do not match selected granularity')
            row[key] = value
        for key in ('campaign_name','adset_name','ad_name'):
            row[key] = raw.get(key,'').strip()[:200]
        key = tuple(row[k] for k in ('account_id','day','campaign_id','adset_id','ad_id'))
        if key in keys:
            raise ValueError('Duplicate daily entity row in file')
        keys.add(key)
        rows.append(row)
    if not rows:
        raise ValueError('CSV has no data rows')
    return rows
