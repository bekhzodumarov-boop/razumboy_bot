from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import json
import subprocess
import sys

from analytics import Analytics, parse_event_link, report


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'report.sqlite'
        self.journal = Analytics(self.path)
        self.sequence = 0

    def event(self, name, *, attempt=None, game=50, when='2026-10-20T10:00:00.000Z',
              step='start', result='ok', source='instagram', user=42):
        self.sequence += 1
        key = str(self.sequence)
        self.journal.record(name, user, key=key, attempt_id=attempt, event_id=game,
                            step=step, result=result, source=source)
        with self.journal.connect() as conn:
            conn.execute('UPDATE funnel_events SET timestamp=? WHERE dedup_key=?', (when,key))

    def test_game_interval_metrics_and_all_outcomes(self):
        self.event('bot_started')
        self.event('bot_started', game=51)
        self.event('bot_started', when='2026-10-21T00:00:00.000Z')
        for attempt in ('complete', 'open', 'cancel', 'technical', 'duplicate', 'replaced'):
            self.event('registration_started', attempt=attempt)
            self.event('registration_step_completed', attempt=attempt, step='team_name')
        self.event('registration_completed', attempt='complete', step='confirm')
        self.event('registration_cancelled', attempt='cancel', result='cancelled')
        self.event('registration_failed', attempt='technical', result='handler_error', step='phone')
        self.event('registration_failed', attempt='duplicate', result='duplicate', step='confirm')
        self.event('registration_cancelled', attempt='replaced', result='superseded')
        self.event('registration_started', attempt='other-game', game=51)
        out = report(self.path, event_id=50, date_from='2026-10-20', date_to='2026-10-21')
        self.assertEqual(out['bot_starts'], 1)
        self.assertEqual(out['registrations_started'], 6)
        self.assertEqual(out['registrations_completed'], 1)
        self.assertEqual(out['steps'], {'team_name': 6})
        self.assertEqual(out['outcome_counts'], dict(unfinished=1, cancelled=1, technical_errors=1,
                                                    duplicates=1, superseded=1, unavailable=0, completed=1))
        self.assertEqual(out['unfinished'][0]['expected_step'], 'team_size')
        self.assertEqual(out['unfinished'][0]['last_completed_step'], 'team_name')
        self.assertEqual(out['technical_errors'][0]['expected_step'], 'phone')

    def test_asof_cutoff_no_future_game_or_completion_leakage(self):
        self.event('registration_started', attempt='menu', game=None, source='menu')
        self.event('registration_step_completed', attempt='menu', game=None, step='phone', source='menu')
        self.event('registration_step_completed', attempt='menu', step='choose_event', source='menu',
                   when='2026-10-21T09:00:00.000Z')
        self.event('registration_completed', attempt='menu', step='confirm', source='menu',
                   when='2026-10-22T09:00:00.000Z')
        before = report(self.path, event_id=50, date_to='2026-10-21')
        self.assertEqual(before['registrations_started'], 0)
        during = report(self.path, event_id=50, date_from='2026-10-20', date_to='2026-10-22')
        self.assertEqual(during['registrations_started'], 1)
        self.assertEqual(during['steps']['phone'], 1)
        self.assertEqual(during['outcome_counts']['unfinished'], 1)
        after = report(self.path, event_id=50, date_from='2026-10-22', date_to='2026-10-23')
        self.assertEqual(after['registrations_started'], 0)
        self.assertEqual(after['registrations_completed'], 1)
        self.assertEqual(after['outcome_counts']['completed'], 1)

    def test_timezone_boundaries_and_invalid_intervals(self):
        self.event('bot_started', when='2026-10-19T19:00:00.000Z')
        self.event('bot_started', when='2026-10-20T19:00:00.000Z')
        out = report(self.path, date_from='2026-10-20T00:00:00+05:00', date_to='2026-10-21T00:00:00+05:00')
        self.assertEqual(out['bot_starts'], 1)
        for filters in [dict(date_from='bad'), dict(date_from='2026-10-20T12:00:00'),
                        dict(date_from='2026-10-21',date_to='2026-10-20'), dict(event_id=-1), dict(source='private-text')]:
            with self.assertRaises(ValueError):
                report(self.path, **filters)

    def test_recovered_error_not_open_technical_outcome(self):
        self.event('registration_started', attempt='recovered')
        self.event('registration_failed', attempt='recovered', step='phone', result='handler_error')
        self.event('registration_step_completed', attempt='recovered', step='phone')
        self.event('registration_completed', attempt='recovered', step='confirm')
        out = report(self.path)
        self.assertEqual(out['technical_error_events'], 1)
        self.assertEqual(out['technical_errors'], [])
        self.assertEqual(out['outcome_counts']['completed'], 1)

    def test_sources_step_attempts_vs_revisions_and_unlinked_errors(self):
        self.event('registration_started', attempt='edit')
        self.event('registration_step_completed', attempt='edit', step='phone')
        self.event('registration_step_completed', attempt='edit', step='phone')
        self.event('bot_started', source='qr', user=43)
        self.event('registration_failed', result='state_lost', step='confirm', source='unknown')
        out = report(self.path, source='instagram')
        self.assertEqual(out['steps']['phone'], 1)
        self.assertEqual(out['step_events']['phone'], 2)
        self.assertEqual(out['unique_starters'], 0)
        self.assertEqual(report(self.path)['technical_error_events'], 1)
        self.assertEqual(len(report(self.path)['unlinked_failures']), 1)

    def test_old_journal_read_only_and_idempotent_upgrade(self):
        self.event('bot_started')
        with self.journal.connect() as conn:
            conn.execute('ALTER TABLE funnel_events DROP COLUMN source')
        self.assertEqual(report(self.path, source='unknown')['bot_starts'], 1)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertNotIn('source', {r[1] for r in conn.execute('PRAGMA table_info(funnel_events)')})
        Analytics(self.path)
        Analytics(self.path)
        self.event('bot_started', source='private-phone-value')
        with self.journal.connect() as conn:
            self.assertEqual({r[0] for r in conn.execute('SELECT source FROM funnel_events')}, {'unknown'})

    def test_cli_filters_readonly_and_error_exit(self):
        self.event('bot_started')
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'analytics.py'), str(self.path)]
        outcome = subprocess.run(command + ['--event-id','50','--from','2026-10-20',
                                            '--until','2026-10-21','--source','instagram'],
                                 capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(outcome.stdout)['bot_starts'], 1)
        invalid = subprocess.run(command + ['--from','bad'], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn('Traceback', invalid.stderr)
        # Building the Dispatcher must never load production .env/config.
        probe = ("from unittest.mock import patch\n"
                 "with patch('dotenv.load_dotenv', side_effect=AssertionError('dotenv forbidden')):\n"
                 " import app\n")
        subprocess.run([sys.executable, '-c', probe], cwd=Path(__file__).resolve().parents[1],
                       capture_output=True, text=True, check=True)

    def test_legacy_and_tagged_links(self):
        self.assertEqual(parse_event_link('event_50'), (50, 'direct'))
        self.assertEqual(parse_event_link('event_50_src_instagram'), (50, 'instagram'))
        self.assertEqual(parse_event_link('event_50_src_private-name'), (50, 'unknown'))
        for invalid in ('event_0', 'event_-50', 'event_50_src_+998901234567', 'event_50junk', 'event_'+'9'*100):
            self.assertEqual(parse_event_link(invalid), (None, 'unknown'))


if __name__ == '__main__':
    unittest.main()
