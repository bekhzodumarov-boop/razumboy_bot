"""Admin-entered attendance and cash ledger. No payment-provider API calls.

All money is integer UZS. Booking and confirmation tables are never rewritten.
Mutations use SQLite transactions, optimistic revisions and an audit operation key.
"""
from contextlib import contextmanager
import csv
import html
import io
import json
import re
import sqlite3

METHODS = {'uzum': 'Uzum', 'payme': 'Payme', 'click': 'Click',
           'card': 'Перевод на карту', 'cash': 'Наличные'}
TEMPLATES = (
    ('dinner', 'Ужин на игре', 500000, 'cost'),
    ('shohruh', 'Оплата Шохруху', None, 'cost'),
    ('timur', 'Оплата Тимуру', None, 'cost'),
    ('assistant', 'Оплата второму помощнику', None, 'cost'),
    ('photographer', 'Оплата фотографу', None, 'cost'),
    ('farruh', 'Прибыль Фарруху', None, 'distribution'),
)


class FinanceError(ValueError):
    pass


def integer(value, maximum, label='Значение'):
    if type(value) is not int or not 0 <= value <= maximum:
        raise FinanceError(f'{label}: допустимо целое число от 0 до {maximum}')
    return value


def parse_integer(text, maximum):
    value = re.sub(r'[ \u00a0\u202f,_]', '', text or '')
    if not re.fullmatch(r'[0-9]{1,15}', value):
        raise FinanceError('Введите целое число без знака и дробной части')
    return integer(int(value), maximum)


def money(value):
    return f'{value:,}'.replace(',', ' ') + ' сум'


def parse_payment_lines(text):
    """Complete team payment breakdown; optional explicit amount after '='."""
    aliases = {'uzum':'uzum','узум':'uzum', 'payme':'payme','пейми':'payme',
               'пайми':'payme','пейме':'payme','пайме':'payme','пэйми':'payme',
               'click':'click','клик':'click','карта':'card','перевод':'card',
               'перевод на карту':'card','наличные':'cash','нал':'cash','наличка':'cash'}
    rows, total = {}, None
    if not text or len(text)>2000:
        raise FinanceError('Отправьте способы и количество игроков, по одному на строку')
    for line in re.split(r'[\n;]',text):
        line = ' '.join(line.lower().split()).strip()
        if not line:
            continue
        match = re.fullmatch(r'итого\s*:?\s*([0-9]+)',line)
        if match:
            if total is not None:
                raise FinanceError('Строка «Итого» должна быть только одна')
            total = parse_integer(match[1],500)
            continue
        match = re.fullmatch(r'([a-zа-я ]+?)\s*:?\s+([0-9]+)(?:\s*=\s*([0-9 ,_\u00a0\u202f]+))?',line)
        if not match or match[1] not in aliases:
            raise FinanceError('Не понял строку. Пример: Узум 2. Для другой суммы: Узум 2 = 130000')
        method = aliases[match[1]]
        if method in rows:
            raise FinanceError(f'{METHODS[method]} указан дважды. Оставьте одну строку с итогом')
        rows[method] = {'players':parse_integer(match[2],500),
                        'amount_uzs':parse_integer(match[3],10**12) if match[3] else None}
    if not rows:
        raise FinanceError('Укажите хотя бы один способ оплаты, например: Узум 2')
    if total is not None and total != sum(x['players'] for x in rows.values()):
        raise FinanceError('«Итого» не совпадает с суммой игроков по способам. Ничего не сохранено')
    return rows, total


class FinanceStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS finance_games(
                event_id INTEGER PRIMARY KEY REFERENCES events(id),
                ticket_uzs INTEGER CHECK(ticket_uzs>=0), revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS finance_teams(
                id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id),
                registration_id INTEGER UNIQUE REFERENCES registrations(id),
                name TEXT NOT NULL, actual_players INTEGER CHECK(actual_players>=0),
                revision INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS finance_teams_event ON finance_teams(event_id);
            CREATE TABLE IF NOT EXISTS finance_payments(
                team_id INTEGER NOT NULL REFERENCES finance_teams(id),
                method TEXT NOT NULL CHECK(method IN ('uzum','payme','click','card','cash')),
                players INTEGER NOT NULL CHECK(players>=0),
                amount_uzs INTEGER NOT NULL CHECK(amount_uzs>=0),
                PRIMARY KEY(team_id,method));
            CREATE TABLE IF NOT EXISTS finance_expenses(
                id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id),
                template_key TEXT, title TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('cost','distribution')),
                suggested_uzs INTEGER, amount_uzs INTEGER CHECK(amount_uzs>=0),
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','excluded')),
                revision INTEGER NOT NULL DEFAULT 0, UNIQUE(event_id,template_key));
            CREATE TABLE IF NOT EXISTS finance_audit(
                id INTEGER PRIMARY KEY, operation_key TEXT NOT NULL UNIQUE,
                event_id INTEGER NOT NULL, actor_id INTEGER NOT NULL,
                action TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            ''')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _event(c, event_id):
        row = c.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        if row is None:
            raise FinanceError('Игра не найдена')
        return dict(row)

    def games(self, page=0):
        with self.connect() as c:
            return [dict(r) for r in c.execute(
                'SELECT id,title,event_date FROM events ORDER BY event_date DESC,id DESC LIMIT 11 OFFSET ?', (page*10,))]

    def prepare(self, event_id):
        """Idempotent additive setup; attendance, money and price stay unknown."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._event(c, event_id)
            c.execute('INSERT OR IGNORE INTO finance_games(event_id) VALUES(?)', (event_id,))
            c.execute('''INSERT OR IGNORE INTO finance_teams(event_id,registration_id,name)
                         SELECT event_id,id,CASE WHEN trim(team_name)='' THEN 'Без команды' ELSE team_name END
                         FROM registrations WHERE event_id=?''', (event_id,))
            for key, title, amount, kind in TEMPLATES:
                c.execute('''INSERT OR IGNORE INTO finance_expenses
                             (event_id,template_key,title,kind,suggested_uzs) VALUES(?,?,?,?,?)''',
                          (event_id, key, title, kind, amount))

    @staticmethod
    def _team(c, team_id):
        t = c.execute('SELECT * FROM finance_teams WHERE id=?', (team_id,)).fetchone()
        if t is None:
            raise FinanceError('Команда не найдена')
        return dict(t)

    @staticmethod
    def _revision(row, expected):
        if row['revision'] != expected:
            raise FinanceError('Запись уже изменена другим админом. Откройте карточку заново')

    @staticmethod
    def _audit(c, operation, event, actor, action, before, after):
        if not isinstance(operation, str) or not 8 <= len(operation) <= 100:
            raise FinanceError('Некорректная операция')
        c.execute('''INSERT INTO finance_audit(operation_key,event_id,actor_id,action,before_json,after_json)
                     VALUES(?,?,?,?,?,?)''', (operation, event, actor, action,
                     json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))

    @contextmanager
    def mutation(self, operation):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            exists = c.execute('SELECT 1 FROM finance_audit WHERE operation_key=?', (operation,)).fetchone()
            yield None if exists else c

    def team(self, team_id):
        with self.connect() as c:
            t = self._team(c, team_id)
            t['payments'] = {r['method']: dict(r) for r in c.execute(
                'SELECT * FROM finance_payments WHERE team_id=?', (team_id,))}
            return t

    def attendance(self, team_id, players, revision, actor, operation):
        if players is not None:
            integer(players, 500, 'Пришло игроков')
        with self.mutation(operation) as c:
            if c is None:
                return
            t = self._team(c, team_id)
            self._revision(t, revision)
            paid = c.execute('SELECT COALESCE(SUM(players),0) FROM finance_payments WHERE team_id=?', (team_id,)).fetchone()[0]
            if paid > (players or 0):
                raise FinanceError('Оплативших больше новой явки. Сначала исправьте оплаты')
            c.execute('UPDATE finance_teams SET actual_players=?,revision=revision+1 WHERE id=?', (players, team_id))
            self._audit(c, operation, t['event_id'], actor, 'attendance', t,
                        {'team_id': team_id, 'actual_players': players})

    def payment(self, team_id, method, players, amount, revision, actor, operation):
        if method not in METHODS:
            raise FinanceError('Неизвестный способ оплаты')
        integer(players, 500, 'Оплатило игроков')
        integer(amount, 10**12, 'Сумма')
        if (players == 0) != (amount == 0):
            raise FinanceError('Число оплативших и сумма должны быть положительными либо оба равны нулю')
        with self.mutation(operation) as c:
            if c is None:
                return
            t = self._team(c, team_id)
            self._revision(t, revision)
            if t['actual_players'] is None:
                raise FinanceError('Сначала подтвердите фактическую явку команды')
            others = c.execute('SELECT COALESCE(SUM(players),0) FROM finance_payments WHERE team_id=? AND method!=?', (team_id, method)).fetchone()[0]
            if players + others > t['actual_players']:
                raise FinanceError('Сумма оплативших по всем способам превышает явку команды')
            before = [dict(r) for r in c.execute('SELECT * FROM finance_payments WHERE team_id=?', (team_id,))]
            c.execute('''INSERT INTO finance_payments(team_id,method,players,amount_uzs) VALUES(?,?,?,?)
                         ON CONFLICT(team_id,method) DO UPDATE SET players=excluded.players,amount_uzs=excluded.amount_uzs''',
                      (team_id, method, players, amount))
            c.execute('UPDATE finance_teams SET revision=revision+1 WHERE id=?', (team_id,))
            self._audit(c, operation, t['event_id'], actor, 'payment_total', before,
                        {'team_id': team_id, 'method': method, 'players': players, 'amount_uzs': amount})

    def ticket(self, event_id, amount, revision, actor, operation):
        integer(amount, 10**9, 'Цена билета')
        with self.mutation(operation) as c:
            if c is None:
                return
            row = dict(c.execute('SELECT * FROM finance_games WHERE event_id=?', (event_id,)).fetchone() or {})
            if not row:
                raise FinanceError('Сначала откройте игру в разделе Явка')
            self._revision(row, revision)
            c.execute('UPDATE finance_games SET ticket_uzs=?,revision=revision+1 WHERE event_id=?', (amount, event_id))
            self._audit(c, operation, event_id, actor, 'ticket_price', row, {'ticket_uzs': amount})

    def batch_payment(self, team_id, rows, total, revision, price_revision, actor, operation):
        """Atomically replace ALL methods, priced inside the same transaction."""
        if not rows or any(method not in METHODS for method in rows):
            raise FinanceError('Неизвестный или пустой список способов оплаты')
        with self.mutation(operation) as c:
            if c is None:
                return
            t = self._team(c,team_id)
            self._revision(t,revision)
            settings = dict(c.execute('SELECT * FROM finance_games WHERE event_id=?',(t['event_id'],)).fetchone())
            if settings['revision'] != price_revision:
                raise FinanceError('Цена игры изменилась. Откройте карточку команды заново')
            if t['actual_players'] is None:
                raise FinanceError('Сначала укажите фактическую явку команды')
            payments = []
            for method in METHODS:
                row = rows.get(method,{'players':0,'amount_uzs':0})
                players = integer(row['players'],500,'Оплатило игроков')
                amount = row.get('amount_uzs')
                if amount is None:
                    if players and not settings['ticket_uzs']:
                        raise FinanceError('Задайте цену билета или сумму в строке: Узум 2 = 130000')
                    amount = players*(settings['ticket_uzs'] or 0)
                integer(amount,10**12,'Сумма')
                if (players == 0) != (amount == 0):
                    raise FinanceError('Число оплативших и сумма должны быть положительными либо оба равны нулю')
                payments.append({'method':method,'players':players,'amount_uzs':amount})
            paid = sum(x['players'] for x in payments)
            if total is not None and integer(total,500,'Итого') != paid:
                raise FinanceError('«Итого» не совпадает с суммой игроков. Ничего не сохранено')
            if paid > t['actual_players']:
                raise FinanceError(f"Оплативших {paid}, а пришло {t['actual_players']}. Ничего не сохранено")
            before = [dict(r) for r in c.execute('SELECT * FROM finance_payments WHERE team_id=?',(team_id,))]
            for p in payments:
                c.execute('''INSERT INTO finance_payments(team_id,method,players,amount_uzs) VALUES(?,?,?,?)
                    ON CONFLICT(team_id,method) DO UPDATE SET players=excluded.players,amount_uzs=excluded.amount_uzs''',
                    (team_id,p['method'],p['players'],p['amount_uzs']))
            c.execute('UPDATE finance_teams SET revision=revision+1 WHERE id=?',(team_id,))
            self._audit(c,operation,t['event_id'],actor,'payment_breakdown',before,
                        {'team_id':team_id,'payments':payments,'ticket_uzs':settings['ticket_uzs']})

    def expense(self, expense_id, amount, status, revision, actor, operation):
        if status not in ('confirmed', 'excluded'):
            raise FinanceError('Неверный статус расхода')
        integer(amount, 10**12, 'Расход')
        with self.mutation(operation) as c:
            if c is None:
                return
            row = dict(c.execute('SELECT * FROM finance_expenses WHERE id=?', (expense_id,)).fetchone() or {})
            if not row:
                raise FinanceError('Статья не найдена')
            self._revision(row, revision)
            c.execute('UPDATE finance_expenses SET amount_uzs=?,status=?,revision=revision+1 WHERE id=?',
                      (amount if status == 'confirmed' else None, status, expense_id))
            self._audit(c, operation, row['event_id'], actor, 'expense', row,
                        {'expense_id': expense_id, 'status': status, 'amount_uzs': amount if status == 'confirmed' else None})

    def expense_kind(self, expense_id, kind, revision, actor, operation):
        if kind not in ('cost', 'distribution'):
            raise FinanceError('Неизвестный тип статьи')
        with self.mutation(operation) as c:
            if c is None:
                return
            row = dict(c.execute('SELECT * FROM finance_expenses WHERE id=?', (expense_id,)).fetchone() or {})
            if not row:
                raise FinanceError('Статья не найдена')
            if row['template_key'] == 'farruh' and kind != 'distribution':
                raise FinanceError('Выплата Фарруху — распределение прибыли, а не расход')
            self._revision(row, revision)
            c.execute('UPDATE finance_expenses SET kind=?,revision=revision+1 WHERE id=?', (kind, expense_id))
            self._audit(c, operation, row['event_id'], actor, 'expense_kind', row, {'expense_id': expense_id, 'kind': kind})

    def rename_expense(self, expense_id, title, revision, actor, operation):
        title = ' '.join((title or '').split())
        if not title or len(title) > 120:
            raise FinanceError('Название должно содержать от 1 до 120 символов')
        with self.mutation(operation) as c:
            if c is None:
                return
            row = dict(c.execute('SELECT * FROM finance_expenses WHERE id=?', (expense_id,)).fetchone() or {})
            if not row:
                raise FinanceError('Статья не найдена')
            self._revision(row, revision)
            c.execute('UPDATE finance_expenses SET title=?,revision=revision+1 WHERE id=?', (title, expense_id))
            self._audit(c, operation, row['event_id'], actor, 'expense_title', row, {'expense_id': expense_id, 'title': title})

    def add(self, event_id, title, kind, amount, actor, operation):
        title = ' '.join((title or '').split())
        if not title or len(title) > 120:
            raise FinanceError('Название должно содержать от 1 до 120 символов')
        if kind not in ('team', 'cost', 'distribution'):
            raise FinanceError('Неизвестная категория')
        if kind != 'team':
            integer(amount, 10**12, 'Сумма')
        with self.mutation(operation) as c:
            if c is None:
                return
            self._event(c, event_id)
            if kind == 'team':
                cur = c.execute('INSERT INTO finance_teams(event_id,name) VALUES(?,?)', (event_id, title))
            else:
                cur = c.execute('''INSERT INTO finance_expenses(event_id,title,kind,amount_uzs,status)
                                   VALUES(?,?,?,?,'confirmed')''', (event_id, title, kind, amount))
            self._audit(c, operation, event_id, actor, 'add_'+kind, {},
                        {'id': cur.lastrowid, 'title': title, 'amount_uzs': amount if kind != 'team' else None})

    def snapshot(self, event_id):
        """A single read transaction for internally consistent counts and money."""
        with self.connect() as c:
            c.execute('BEGIN')
            event = self._event(c, event_id)
            settings = dict(c.execute('SELECT * FROM finance_games WHERE event_id=?', (event_id,)).fetchone() or {})
            teams = [dict(r) for r in c.execute('''SELECT t.*,r.status AS booking_status,r.team_size AS booked_players
                        FROM finance_teams t LEFT JOIN registrations r ON r.id=t.registration_id
                        WHERE t.event_id=? ORDER BY t.id''', (event_id,))]
            payments = [dict(r) for r in c.execute('''SELECT p.* FROM finance_payments p
                       JOIN finance_teams t ON t.id=p.team_id WHERE t.event_id=?''', (event_id,))]
            expenses = [dict(r) for r in c.execute('SELECT * FROM finance_expenses WHERE event_id=? ORDER BY id', (event_id,))]
            registered = c.execute("SELECT COUNT(*),COALESCE(SUM(team_size),0) FROM registrations WHERE event_id=? AND status='confirmed'", (event_id,)).fetchone()
        by_method = {m: {'players': 0, 'amount_uzs': 0} for m in METHODS}
        for p in payments:
            by_method[p['method']]['players'] += p['players']
            by_method[p['method']]['amount_uzs'] += p['amount_uzs']
        income = sum(p['amount_uzs'] for p in payments)
        costs = sum(x['amount_uzs'] for x in expenses if x['status'] == 'confirmed' and x['kind'] == 'cost')
        distributions = sum(x['amount_uzs'] for x in expenses if x['status'] == 'confirmed' and x['kind'] == 'distribution')
        return {'event': event, 'settings': settings, 'teams': teams, 'payments': payments, 'expenses': expenses,
                'registered_teams': registered[0], 'registered_players': registered[1],
                'arrived_teams': sum(t['actual_players'] is not None and t['actual_players'] > 0 for t in teams),
                'actual_players': sum(t['actual_players'] or 0 for t in teams),
                'unknown_teams': sum(t['actual_players'] is None for t in teams),
                'paid_players': sum(p['players'] for p in payments), 'by_method': by_method,
                'income_uzs': income, 'costs_uzs': costs, 'distributions_uzs': distributions,
                'result_uzs': income-costs, 'balance_uzs': income-costs-distributions,
                'pending_expenses': sum(x['status'] == 'pending' for x in expenses)}


def format_report(s):
    e = s['event']
    lines = [f"📊 <b>Игра #{e['id']}: {html.escape(str(e['title'])[:200])}</b>",
             f"Дата: {html.escape(str(e['event_date']))}",
             f"Заявки: {s['registered_teams']} команд / {s['registered_players']} игроков",
             f"Подтвержденная явка: {s['arrived_teams']} команд / {s['actual_players']} игроков",
             f"Явка не отмечена: {s['unknown_teams']} записей",
             f"Оплативших отмечено: {s['paid_players']}",
             f"Явка без отметки оплаты: {s['actual_players']-s['paid_players']} (включая возможные льготы)", '']
    for method, label in METHODS.items():
        v = s['by_method'][method]
        lines.append(f"{label}: {v['players']} чел. / {money(v['amount_uzs'])}")
    lines += ['', f"Поступления: <b>{money(s['income_uzs'])}</b>",
              f"Подтвержденные расходы: {money(s['costs_uzs'])}",
              f"Результат по учтенным статьям: {money(s['result_uzs'])}",
              f"Распределено соучредителям: {money(s['distributions_uzs'])} (не расход)",
              f"Остаток после расходов и распределения: {money(s['balance_uzs'])}",
              f"Статей без решения: {s['pending_expenses']}",
              'Все суммы в UZS. Это ручной учет, не банковская проверка платежей.',
              'Результат не равен окончательной прибыли, пока явка, оплаты и расходы не сверены.']
    return '\n'.join(lines)


def export_csv(s):
    buf = io.StringIO(newline='')
    w = csv.writer(buf)
    def safe(v):
        value = str(v if v is not None else '')
        return "'"+value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    w.writerow(['Тип', 'Название', 'Статус', 'Игроков', 'Сумма UZS', 'Способ оплаты'])
    for t in s['teams']:
        w.writerow(['Явка', safe(t['name']), 'не отмечена' if t['actual_players'] is None else 'не пришли' if t['actual_players']==0 else 'пришли', t['actual_players'], '', ''])
        for p in s['payments']:
            if p['team_id'] == t['id']:
                w.writerow(['Оплата', safe(t['name']), 'внесено админом', p['players'], p['amount_uzs'], METHODS[p['method']]])
    for x in s['expenses']:
        w.writerow(['Расход' if x['kind']=='cost' else 'Распределение прибыли', safe(x['title']), x['status'], '', x['amount_uzs'], ''])
    for key, label in [('income_uzs','Поступления'),('costs_uzs','Расходы'),('result_uzs','Результат по учтенным статьям'),('distributions_uzs','Распределено соучредителям'),('balance_uzs','Остаток')]:
        w.writerow(['Итог',label,'','',s[key],''])
    return buf.getvalue().encode('utf-8-sig')
