"""Aggregate-only audit of an explicitly confirmed, standalone SQLite backup.

Standard library only. No bot/config imports, migrations, network or list exports.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3

REQUIRED = {
    'users': {'id', 'telegram_id', 'phone', 'subscribed', 'is_admin', 'created_at'},
    'subscribers_profile': {'telegram_id', 'phone', 'created_at'},
    'registrations': {'user_id', 'event_id', 'phone', 'status', 'created_at'},
    'referrals': {'referrer_telegram_id', 'referred_telegram_id', 'qualified', 'joined_at', 'qualified_at'},
}


def normalized_phone(value):
    """Uzbekistan format only; syntactic validity, not ownership or reachability."""
    if not isinstance(value, str):
        return None
    compact = re.sub(r'[ ()\-\s]', '', value)
    if not re.fullmatch(r'\+?998[0-9]{9}', compact):
        return None
    digits = compact.lstrip('+')
    return '+' + digits if digits[3:] != '000000000' else None


def timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def sql_timestamp(value):
    parsed = timestamp(value)
    return parsed.isoformat() if parsed else None


@contextmanager
def open_backup(path, *, confirmed_local_backup=False):
    if not confirmed_local_backup:
        raise ValueError('backup_confirmation_required')
    raw = str(path)
    if raw.startswith(('\\\\', '//')) or '://' in raw:
        raise ValueError('local_backup_required')
    target = Path(path).resolve(strict=True)
    if not target.is_file() or Path('/data').resolve() in target.parents:
        raise ValueError('standalone_backup_required')
    if target == Path(__file__).resolve().parent / 'razumboy.db':
        raise ValueError('project_database_not_allowed')
    if any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('standalone_backup_required')
    # Immutable is safe only for an offline snapshot. Refuse live WAL sidecars above.
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro&immutable=1', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, columns in REQUIRED.items():
            if table not in tables:
                raise ValueError('unsupported_schema')
            available = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
            if not columns <= available:
                raise ValueError('unsupported_schema')
        conn.create_function('audit_phone', 1, normalized_phone, deterministic=True)
        conn.create_function('audit_timestamp', 1, sql_timestamp, deterministic=True)
        yield conn


def analyze_backup(path, *, confirmed_local_backup=False, as_of=None):
    end = timestamp(as_of) if as_of else datetime.now(timezone.utc)
    if end is None or (as_of and datetime.fromisoformat(as_of.replace('Z', '+00:00')).tzinfo is None):
        raise ValueError('as_of_requires_timezone')
    with open_backup(path, confirmed_local_backup=confirmed_local_backup) as conn:
        def count(sql, params=()):
            return conn.execute(sql, params).fetchone()[0]

        totals = {table: count(f'SELECT COUNT(*) FROM {table}') for table in REQUIRED}
        subscriptions = {
            'flag_1': count('SELECT COUNT(*) FROM users WHERE subscribed=1'),
            'flag_0': count('SELECT COUNT(*) FROM users WHERE subscribed=0'),
            'invalid_or_null': count('SELECT COUNT(*) FROM users WHERE subscribed IS NULL OR subscribed NOT IN (0,1)'),
            'flag_1_without_profile': count('''SELECT COUNT(*) FROM users u WHERE subscribed=1
                AND NOT EXISTS (SELECT 1 FROM subscribers_profile p WHERE p.telegram_id=u.telegram_id)'''),
            'profiles_linked_to_flag_0': count('''SELECT COUNT(*) FROM subscribers_profile p JOIN users u
                ON p.telegram_id=u.telegram_id WHERE u.subscribed=0'''),
        }
        phones = {}
        for table in ('users','subscribers_profile','registrations'):
            valid = count(f'SELECT COUNT(*) FROM {table} WHERE audit_phone(phone) IS NOT NULL')
            unique = count(f'SELECT COUNT(DISTINCT audit_phone(phone)) FROM {table}')
            missing = count(f"SELECT COUNT(*) FROM {table} WHERE phone IS NULL OR trim(phone)=''")
            phones[table] = dict(valid_rows=valid, unique_valid=unique, missing=missing,
                                 invalid_or_unsupported=totals[table]-valid-missing,
                                 repeated_valid_rows=valid-unique)
        phone_sets = {table: f'SELECT audit_phone(phone) AS phone FROM {table} WHERE audit_phone(phone) IS NOT NULL'
                      for table in phones}
        phones['union_unique_valid'] = count('SELECT COUNT(*) FROM ('+' UNION '.join(phone_sets.values())+')')
        phones['pairwise_shared_unique'] = {
            f'{left}__{right}': count(f'SELECT COUNT(*) FROM ({phone_sets[left]} INTERSECT {phone_sets[right]})')
            for left,right in (('users','subscribers_profile'),('users','registrations'),('subscribers_profile','registrations'))}
        account_sets = {
            'users': 'SELECT telegram_id FROM users',
            'profiles': 'SELECT telegram_id FROM subscribers_profile',
            'registrations': '''SELECT u.telegram_id FROM registrations r JOIN users u ON u.id=r.user_id''',
            'referrals': '''SELECT referrer_telegram_id FROM referrals UNION SELECT referred_telegram_id FROM referrals''',
        }
        overlaps = {}
        labels = list(account_sets)
        for index,left in enumerate(labels):
            for right in labels[index+1:]:
                overlaps[f'{left}__{right}'] = count(f'''SELECT COUNT(*) FROM (
                    SELECT * FROM ({account_sets[left]}) INTERSECT SELECT * FROM ({account_sets[right]}))''')
        overlaps['users_profiles_registrations'] = count(f'''SELECT COUNT(*) FROM (
            {account_sets['users']} INTERSECT {account_sets['profiles']} INTERSECT {account_sets['registrations']})''')

        def captains(where):
            groups = f'''SELECT r.user_id,COUNT(*) n FROM registrations r JOIN users u ON u.id=r.user_id
                         WHERE {where} GROUP BY r.user_id'''
            return {label: count(f'SELECT COUNT(*) FROM ({groups}) WHERE {condition}')
                    for label,condition in (('one','n=1'),('two','n=2'),('three_plus','n>=3'))}

        anomalies = {
            'profiles_without_user': count('''SELECT COUNT(*) FROM subscribers_profile p WHERE NOT EXISTS
                (SELECT 1 FROM users u WHERE u.telegram_id=p.telegram_id)'''),
            'registrations_without_user': count('''SELECT COUNT(*) FROM registrations r WHERE NOT EXISTS
                (SELECT 1 FROM users u WHERE u.id=r.user_id)'''),
            'referrals_missing_referrer': count('''SELECT COUNT(*) FROM referrals r WHERE NOT EXISTS
                (SELECT 1 FROM users u WHERE u.telegram_id=r.referrer_telegram_id)'''),
            'referrals_missing_referred': count('''SELECT COUNT(*) FROM referrals r WHERE NOT EXISTS
                (SELECT 1 FROM users u WHERE u.telegram_id=r.referred_telegram_id)'''),
            'self_referrals': count('SELECT COUNT(*) FROM referrals WHERE referrer_telegram_id=referred_telegram_id'),
            'duplicate_confirmed_user_game_pairs': count('''SELECT COUNT(*) FROM (
                SELECT user_id,event_id FROM registrations WHERE status='confirmed'
                GROUP BY user_id,event_id HAVING COUNT(*)>1)'''),
            'accounts_with_profile_registration_phone_difference': count('''SELECT COUNT(DISTINCT u.id)
                FROM users u JOIN subscribers_profile p ON p.telegram_id=u.telegram_id
                JOIN registrations r ON r.user_id=u.id WHERE audit_phone(p.phone) IS NOT NULL
                AND audit_phone(r.phone) IS NOT NULL AND audit_phone(p.phone)!=audit_phone(r.phone)'''),
            'phones_shared_across_accounts': count('''SELECT COUNT(*) FROM (
                SELECT phone FROM (
                  SELECT telegram_id,audit_phone(phone) phone FROM users
                  UNION SELECT telegram_id,audit_phone(phone) FROM subscribers_profile
                  UNION SELECT u.telegram_id,audit_phone(r.phone) FROM registrations r JOIN users u ON u.id=r.user_id)
                WHERE phone IS NOT NULL GROUP BY phone HAVING COUNT(DISTINCT telegram_id)>1)'''),
        }
        activity = {}
        date_columns = {'users':'created_at','subscribers_profile':'created_at',
                        'registrations':'created_at','referrals':'joined_at'}
        timestamp_quality = {table: count(f'SELECT COUNT(*) FROM {table} WHERE audit_timestamp({column}) IS NULL')
                             for table,column in date_columns.items()}
        for days in (90,180):
            bounds = ((end-timedelta(days=days)).isoformat(),end.isoformat())
            recent = {table: count(f'''SELECT COUNT(*) FROM {table}
                        WHERE audit_timestamp({column})>=? AND audit_timestamp({column})<?''', bounds)
                      for table,column in date_columns.items()}
            recent['registration_accounts'] = count('''SELECT COUNT(DISTINCT u.id) FROM users u
                JOIN registrations r ON r.user_id=u.id WHERE audit_timestamp(r.created_at)>=?
                AND audit_timestamp(r.created_at)<?''', bounds)
            recent['confirmed_registration_accounts'] = count('''SELECT COUNT(DISTINCT u.id) FROM users u
                JOIN registrations r ON r.user_id=u.id WHERE r.status='confirmed'
                AND audit_timestamp(r.created_at)>=? AND audit_timestamp(r.created_at)<?''', bounds)
            recent['non_admin_confirmed_captains_with_phone'] = count('''SELECT COUNT(DISTINCT u.id)
                FROM users u JOIN registrations r ON r.user_id=u.id WHERE u.is_admin=0
                AND r.status='confirmed' AND audit_phone(r.phone) IS NOT NULL
                AND audit_timestamp(r.created_at)>=? AND audit_timestamp(r.created_at)<?''', bounds)
            # Referral creation is evidence about the referred account, not referrer activity.
            recent['accounts_with_observed_creation_activity'] = count('''SELECT COUNT(*) FROM (
                SELECT u.id FROM users u WHERE audit_timestamp(u.created_at)>=? AND audit_timestamp(u.created_at)<?
                UNION SELECT u.id FROM users u JOIN subscribers_profile p ON p.telegram_id=u.telegram_id
                  WHERE audit_timestamp(p.created_at)>=? AND audit_timestamp(p.created_at)<?
                UNION SELECT u.id FROM users u JOIN registrations r ON r.user_id=u.id
                  WHERE audit_timestamp(r.created_at)>=? AND audit_timestamp(r.created_at)<?
                UNION SELECT u.id FROM users u JOIN referrals r ON r.referred_telegram_id=u.telegram_id
                  WHERE audit_timestamp(r.joined_at)>=? AND audit_timestamp(r.joined_at)<?)''', bounds*4)
            activity[f'last_{days}_days'] = recent

        segments = {}
        for minimum in (1,2,3):
            segments[f'non_admin_captains_confirmed_{minimum}_plus_with_phone'] = count('''
                SELECT COUNT(*) FROM (SELECT r.user_id FROM registrations r JOIN users u ON u.id=r.user_id
                  WHERE u.is_admin=0 AND r.status='confirmed' GROUP BY r.user_id HAVING COUNT(*)>=?
                  AND MAX(audit_phone(r.phone) IS NOT NULL)=1)''', (minimum,))
        segments['subscribed_profiles_with_phone_non_admin'] = count('''SELECT COUNT(DISTINCT u.id)
            FROM users u JOIN subscribers_profile p ON p.telegram_id=u.telegram_id
            WHERE u.is_admin=0 AND u.subscribed=1 AND audit_phone(p.phone) IS NOT NULL''')
        segments['profile_accounts_without_confirmed_registration_with_phone_non_admin'] = count('''SELECT COUNT(DISTINCT u.id)
            FROM users u JOIN subscribers_profile p ON p.telegram_id=u.telegram_id WHERE u.is_admin=0
            AND audit_phone(p.phone) IS NOT NULL AND NOT EXISTS
            (SELECT 1 FROM registrations r WHERE r.user_id=u.id AND r.status='confirmed')''')
        segments['qualified_referred_profiles_with_phone_non_admin'] = count('''SELECT COUNT(DISTINCT u.id)
            FROM users u JOIN subscribers_profile p ON p.telegram_id=u.telegram_id
            JOIN referrals r ON r.referred_telegram_id=u.telegram_id
            WHERE u.is_admin=0 AND r.qualified=1 AND audit_phone(p.phone) IS NOT NULL''')
        schema_names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        consent_hints = sum(bool(re.search('consent|соглас', name, re.I)) for name in schema_names)
        for table in REQUIRED:
            consent_hints += sum(bool(re.search('consent|соглас', r['name'], re.I))
                                 for r in conn.execute(f'PRAGMA table_info({table})'))

        return dict(as_of_exclusive_utc=end.isoformat(), totals=totals, subscriptions=subscriptions,
                    phones=phones, account_overlaps=overlaps,
                    captains=dict(all_registration_rows=captains('1=1'),
                                  currently_confirmed_rows=captains("r.status='confirmed'")),
                    anomalies=anomalies, activity=activity, invalid_or_missing_timestamps=timestamp_quality,
                    potential_segments_counts_only=segments,
                    advertising_consent=dict(schema_name_hints=consent_hints,
                        evidence_verified=False, advertising_eligibility='not_verified_do_not_export'),
                    limitations=['counts_are_accounts_not_verified_people',
                                 'phone_format_is_not_ownership_verification',
                                 'creation_timestamps_are_not_last_seen',
                                 'referral_qualification_time_excluded_timezone_unspecified',
                                 'subscription_flag_is_not_advertising_consent'])


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Invalid audit arguments. Use --help.\n')


def main():
    parser = SafeParser(description='Aggregate-only audit of a standalone local backup; no network or exports.')
    parser.add_argument('backup', help='Explicit standalone local SQLite snapshot')
    parser.add_argument('--confirm-local-backup', action='store_true', required=True)
    parser.add_argument('--as-of', help='Exclusive cutoff with UTC offset; default: current UTC time')
    args = parser.parse_args()
    try:
        result = analyze_backup(args.backup, confirmed_local_backup=args.confirm_local_backup, as_of=args.as_of)
    except (ValueError, OSError, sqlite3.Error, OverflowError):
        parser.exit(2, '{"error":"audit_unavailable_check_backup_schema_and_arguments"}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
