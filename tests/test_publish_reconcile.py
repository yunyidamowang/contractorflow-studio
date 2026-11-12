"""Publish uncertainty, feedback cap, and the circuit breaker.

Fixture databases and a fake HTTP layer only. No socket, model, or ledger file
named state.db.
"""
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
import test_automation
from automation.dispatcher import (
    REPO, ROOT, Blocked, GitHub, _deliver_feedback, recover_open, run_issue,
)
from automation.publish_reconcile import (
    FEEDBACK_MARKER, MAX_FEEDBACK_POSTS, FEEDBACK_WINDOW_MS, CircuitBreaker,
    WriteFailed, classify_blocked, decide_publish, feedback_body, marker_present,
    observe_controls, publish_draft,
)
from automation.task_queue import Queue, QueueBlocked


NOW = 1_700_000_000_000
SHA = 'a' * 40
URL = 'https://example.invalid/pull/1'
CI_SHA256 = '4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d'
EVENT = {'id': 9, 'event': 'labeled', 'label': {'name': 'codex-ready'}, 'actor': {'login': 'owner'}}


def branch_for(issue, attempt=1, tail='99'):
    return f'codex/issue-{issue}-attempt-{attempt}-{tail}'


def activate(path, issue=41, now=NOW):
    return Queue(path).activate(
        repo='example/fixture', issue=issue, authorization_version='auth', trigger='trig',
        day='2026-11-12', max_attempts=2, max_daily=3, now=now)


def to_publishing(path, issue=41, now=NOW):
    hold = activate(path, issue, now)
    for name in ('snapshot', 'model', 'testing', 'publishing'):
        hold.advance(name, now=now)
    return hold


class Script:
    """In-memory GitHub. Records every call and never opens a socket."""

    def __init__(self):
        self.calls = []
        self.comments = []
        self.branch = None
        self.mode = 'ok'
        self.feedback_failures = 0
        self.repo = {'full_name': REPO, 'private': False, 'allow_auto_merge': False}
        self.protected = True
        self.models = 0

    def api(self, method, route, data=None):
        self.calls.append((method, route))
        if method == 'POST' and route == '/git/refs' and isinstance(data, dict):
            self.branch = data.get('ref', '').removeprefix('refs/heads/')
        if method == 'POST' and route.endswith('/comments') and isinstance(data, dict):
            if FEEDBACK_MARKER in data.get('body', '') and self.mode == 'feedback-timeout':
                self.feedback_failures += 1
                if self.feedback_failures == 1:
                    raise Blocked('GitHub timeout failure; request stopped')
            if FEEDBACK_MARKER in data.get('body', ''):
                self.comments.append(data['body'])
            return {'id': 1}
        if method == 'POST' and route == '/git/refs' and self.mode in ('ref-timeout', 'ref-401', 'ref-422', 'get-down'):
            message = {
                'ref-timeout': 'GitHub timeout failure; request stopped',
                'ref-401': 'GitHub http failure HTTP 401; request stopped',
                'ref-422': 'GitHub http failure HTTP 422; request stopped',
                'get-down': 'GitHub timeout failure; request stopped',
            }[self.mode]
            raise Blocked(message)
        if method == 'POST' and route == '/pulls' and self.mode == 'pull-timeout':
            raise Blocked('GitHub connection failure; request stopped')
        if method == 'GET' and route.startswith('/git/ref/heads/codex/'):
            return self._ref()
        if method == 'GET' and route.startswith('/git/commits/'):
            return self._commit()
        if method == 'GET' and route.startswith('/pulls?'):
            return self._pulls()
        if route == '/labels/codex-stop':
            return {'name': 'codex-stop'}
        if route == '':
            return dict(self.repo)
        if route == '/branches/main':
            return {'name': 'main', 'protected': self.protected}
        if method == 'GET' and route.startswith('/issues/'):
            return test_automation.issue()
        if method == 'POST' and route == '/pulls':
            return {'html_url': URL}
        if method == 'POST':
            return {'sha': SHA}
        return {}

    def pages(self, route):
        self.calls.append(('PAGES', route))
        if 'events' in route:
            return [EVENT]
        if 'comments' in route:
            return [{'user': {'login': 'owner'}, 'body': body} for body in self.comments]
        return []

    def _ref(self):
        if self.mode in ('ref-timeout', 'ref-422', 'absent'):
            raise Blocked('GitHub http failure HTTP 404; request stopped')
        if self.mode == 'ref-401':
            raise Blocked('GitHub http failure HTTP 401; request stopped')
        if self.mode == 'get-down':
            raise Blocked('GitHub connection failure; request stopped')
        if self.mode == 'mismatch':
            return {'object': {'sha': 'b' * 40}}
        return {'object': {'sha': SHA}}

    def _commit(self):
        if self.mode in ('ref-timeout', 'ref-422', 'absent'):
            raise Blocked('GitHub http failure HTTP 404; request stopped')
        if self.mode == 'ref-401':
            raise Blocked('GitHub http failure HTTP 401; request stopped')
        if self.mode == 'get-down':
            raise Blocked('GitHub connection failure; request stopped')
        return {'sha': SHA}

    def _pulls(self):
        if self.mode == 'get-down':
            raise Blocked('GitHub connection failure; request stopped')
        if self.mode == 'ref-401':
            raise Blocked('GitHub http failure HTTP 401; request stopped')
        if self.mode in ('pull-timeout', 'present'):
            return [{
                'draft': True,
                'html_url': URL,
                'head': {'ref': self.branch, 'sha': SHA},
                'base': {'ref': 'main'},
            }]
        return []

    def posts(self, route):
        return [call for call in self.calls if call[0] == 'POST' and call[1] == route]


class PublishReconcileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / 'queue.db'
        self.breaker_path = self.root / 'queue.db.breaker'
        Queue(self.db).migrate_up()

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_post_is_single_attempt(self):
        calls = []
        noted = []

        def post(route, data):
            calls.append(route)
            if route == '/git/refs':
                raise WriteFailed('unknown')
            return {'sha': SHA, 'html_url': URL}

        with self.assertRaises(WriteFailed):
            publish_draft(post, lambda name, sha: noted.append((name, sha)), 12, 1, SHA, SHA,
                          [('docs/sample.md', b'SAMPLE\n', '100644')], branch_for(12))
        self.assertEqual(calls.count('/git/refs'), 1)
        self.assertNotIn('/pulls', calls)
        self.assertEqual(noted, [(branch_for(12), SHA)])
        self.assertNotIn('time.sleep', (ROOT / 'automation/publish_reconcile.py').read_text())
        self.assertNotIn('range(', inspect.getsource(publish_draft))

    def test_readonly_decision_covers_exists_absent_partial_and_unknown(self):
        branch = branch_for(12)
        ref = (200, {'object': {'sha': SHA}})
        commit = (200, {'sha': SHA})
        pull = (200, [{'draft': True, 'html_url': URL, 'head': {'ref': branch, 'sha': SHA}, 'base': {'ref': 'main'}}])
        self.assertEqual(decide_publish(ref, pull, commit, branch, SHA), ('exists', URL))
        self.assertEqual(decide_publish((404, None), (200, []), (404, None), branch, SHA), ('absent', None))
        self.assertEqual(decide_publish(ref, (200, []), commit, branch, SHA), ('partial', None))
        self.assertEqual(decide_publish(None, pull, commit, branch, SHA)[0], 'unknown')
        self.assertEqual(decide_publish((401, None), pull, commit, branch, SHA)[0], 'auth')
        self.assertEqual(decide_publish((200, {'object': {'sha': 'b' * 40}}), pull, commit, branch, SHA)[0], 'unknown')
        self.assertEqual(decide_publish(ref, (200, [pull[1][0], dict(pull[1][0])]), commit, branch, SHA)[0], 'unknown')
        odd = dict(pull[1][0], draft=False)
        self.assertEqual(decide_publish(ref, (200, [odd]), commit, branch, SHA)[0], 'unknown')
        self.assertEqual(classify_blocked('GitHub timeout failure; request stopped'), 'unknown')
        self.assertEqual(classify_blocked('GitHub http failure HTTP 401; request stopped'), 'auth')
        self.assertEqual(classify_blocked('GitHub http failure HTTP 503; request stopped'), 'unknown')
        self.assertEqual(classify_blocked('GitHub http failure HTTP 422; request stopped'), 'rejected')
        self.assertIsNone(observe_controls(
            {'full_name': REPO, 'private': False, 'allow_auto_merge': False},
            {'name': 'main', 'protected': True}))
        self.assertEqual(observe_controls(
            {'full_name': REPO, 'private': False, 'allow_auto_merge': True},
            {'name': 'main', 'protected': True}), 'policy')
        self.assertEqual(observe_controls(
            {'full_name': REPO, 'private': False, 'allow_auto_merge': False},
            {'name': 'main', 'protected': False}), 'branch_protection')

    def test_get_retry_separated_from_write_recovery(self):
        source = inspect.getsource(GitHub.api)
        self.assertIn("4 if method == 'GET' else 2", source)
        self.assertNotIn('for ', inspect.getsource(_deliver_feedback))
        with patch('automation.dispatcher.audit'), patch('automation.dispatcher.time.sleep'), \
                patch('urllib.request.build_opener') as factory:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{}'
            factory.return_value.open.side_effect = [TimeoutError(), response]
            self.assertEqual(GitHub('synthetic').api('GET', '/branches/main'), {})
            self.assertEqual(factory.return_value.open.call_count, 2)
            factory.return_value.open.side_effect = urllib.error.HTTPError('secret', 401, 'secret', {}, None)
            factory.return_value.open.reset_mock()
            with self.assertRaises(Blocked):
                GitHub('synthetic').api('POST', '/pulls', {'base': 'main', 'draft': True, 'head': 'codex/issue-12-attempt-1-1'})
            self.assertEqual(factory.return_value.open.call_count, 1)
            with self.assertRaisesRegex(Blocked, 'outside worker capability'):
                GitHub('synthetic').api('GET', '/git/ref/heads/other')
            factory.return_value.open.side_effect = None
            factory.return_value.open.return_value = response
            self.assertEqual(GitHub('synthetic').api('GET', '/git/ref/heads/codex/issue-12-attempt-1-99'), {})

    def test_publish_unknown_survives_restart_without_model(self):
        hold = to_publishing(self.db)
        hold.note_publish_target(branch_for(41), SHA, now=NOW)
        hold.mark_publish_unknown(now=NOW)
        restarted = Queue(self.db)
        self.assertEqual(restarted.fetch(1)['state'], 'publish_unknown')
        self.assertEqual(restarted.fetch(1)['publish_branch'], branch_for(41))
        self.assertEqual(restarted.fetch(1)['model_started'], 1)
        restarted.reconcile(now=NOW + 120_000)
        self.assertEqual(restarted.fetch(1)['state'], 'publish_unknown')
        self.assertEqual(restarted.fetch(1)['attempt'], 1)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            activate(self.db, now=NOW + 120_000)
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        restarted.apply_reconciliation(1, 'exists', url=URL, now=NOW + 120_000)
        self.assertEqual(restarted.fetch(1)['state'], 'feedback_pending')
        self.assertEqual(restarted.fetch(1)['published_url'], URL)
        self.assertEqual(restarted.fetch(1)['model_started'], 1)

    def test_absent_and_partial_do_not_resend(self):
        for outcome, detail in (('absent', 'publish_absent'), ('partial', 'publish_partial')):
            path = self.root / f'{outcome}.db'
            Queue(path).migrate_up()
            hold = to_publishing(path)
            hold.note_publish_target(branch_for(41), SHA, now=NOW)
            hold.mark_publish_unknown(now=NOW)
            Queue(path).apply_reconciliation(1, outcome, now=NOW)
            row = Queue(path).fetch(1)
            self.assertEqual(row['state'], 'blocked')
            self.assertEqual(row['result'], detail)
            self.assertEqual(row['attempt'], 1)
            self.assertEqual(row['model_started'], 1)
            with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
                activate(path)

    def test_undecided_write_latches_and_blocks(self):
        breaker = CircuitBreaker(self.breaker_path)
        hold = to_publishing(self.db)
        hold.note_publish_target(branch_for(41), SHA, now=NOW)
        hold.mark_publish_unknown(now=NOW)
        Queue(self.db, breaker=breaker).apply_reconciliation(1, 'unknown', now=NOW)
        row = Queue(self.db).fetch(1)
        self.assertEqual(row['state'], 'blocked')
        self.assertEqual(row['result'], 'publish_unreconciled')
        self.assertEqual(row['model_started'], 1)
        self.assertEqual(CircuitBreaker(self.breaker_path).reason(), 'unreconcilable_write')
        with self.assertRaisesRegex(QueueBlocked, 'circuit breaker latched'):
            Queue(self.db, breaker=CircuitBreaker(self.breaker_path)).activate(
                repo='example/fixture', issue=99, authorization_version='auth', trigger='other',
                day='2026-11-12', max_attempts=2, max_daily=3, now=NOW)

    def test_marker_already_present(self):
        now = time.time_ns() // 1_000_000
        hold = to_publishing(self.db, issue=12, now=now)
        hold.publish(lambda: URL, now=now)
        script = Script()
        script.comments.append(MARKER_COMMENT)
        api = self._github(script)
        _deliver_feedback(api, Queue(self.db), 1, ('docs/sample.md',), CircuitBreaker(self.breaker_path))
        self.assertEqual(script.posts('/issues/12/comments'), [])
        self.assertEqual(Queue(self.db).fetch(1)['state'], 'review')
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        self.assertFalse(self.breaker_path.exists())
        self.assertTrue(marker_present([{'body': MARKER_COMMENT}], FEEDBACK_MARKER))
        body = feedback_body(URL, ('docs/sample.md',), 1)
        self.assertIn(FEEDBACK_MARKER, body)
        self.assertNotIn('synthetic', body)

    def test_feedback_cap_reached(self):
        now = time.time_ns() // 1_000_000
        hold = to_publishing(self.db, issue=12, now=now)
        hold.publish(lambda: URL, now=now)
        conn = sqlite3.connect(self.db)
        conn.execute('UPDATE cf_task_queue_v1 SET feedback_posts=?, feedback_at=?', (MAX_FEEDBACK_POSTS, now))
        conn.commit()
        conn.close()
        script = Script()
        with self.assertRaises(Blocked):
            _deliver_feedback(self._github(script), Queue(self.db), 1, (), CircuitBreaker(self.breaker_path))
        self.assertEqual(script.posts('/issues/12/comments'), [])
        self.assertEqual(Queue(self.db).fetch(1)['result'], 'feedback_capped')
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        window = self.root / 'window.db'
        Queue(window).migrate_up()
        held = to_publishing(window, issue=12, now=now)
        held.publish(lambda: URL, now=now)
        conn = sqlite3.connect(window)
        conn.execute('UPDATE cf_task_queue_v1 SET feedback_posts=1, feedback_at=?', (now - FEEDBACK_WINDOW_MS - 1,))
        conn.commit()
        conn.close()
        with self.assertRaises(Blocked):
            _deliver_feedback(self._github(Script()), Queue(window), 1, (), CircuitBreaker(self.root / 'window.breaker'))
        self.assertEqual(Queue(window).fetch(1)['result'], 'feedback_capped')
        self.assertEqual(MAX_FEEDBACK_POSTS, 2)

    def test_crash_between_publish_and_feedback(self):
        now = time.time_ns() // 1_000_000
        hold = to_publishing(self.db, issue=12, now=now)
        hold.publish(lambda: URL, now=now)
        self.assertEqual(Queue(self.db).fetch(1)['state'], 'feedback_pending')
        self.assertEqual(Queue(self.db).fetch(1)['feedback_posts'], 0)
        script = Script()
        recover_open(self._github(script), self._config())
        draft = [call for call in script.calls if call[0] == 'POST' and call[1] == '/issues/12/comments']
        self.assertEqual(len(draft), 1)
        self.assertIn(FEEDBACK_MARKER, script.comments[0])
        self.assertNotIn('/git/refs', [call[1] for call in script.calls])
        self.assertEqual(Queue(self.db).fetch(1)['state'], 'review')
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        again = Script()
        again.comments.append(script.comments[0])
        recover_open(self._github(again), self._config())
        self.assertEqual(again.posts('/issues/12/comments'), [])
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            Queue(self.db).activate(
                repo='example/fixture', issue=12, authorization_version='auth', trigger='trig',
                day='2026-11-12', max_attempts=2, max_daily=3, now=now)

    def test_token_expired_latches_breaker(self):
        script = self._run('ref-401')
        self.assertEqual(len(script.posts('/git/refs')), 1)
        self.assertEqual(script.posts('/pulls'), [])
        self.assertEqual(script.models, 1)
        self.assertEqual(CircuitBreaker(self.breaker_path).reason(), 'auth')
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        self.assertNotEqual(Queue(self.db).fetch(1)['state'], 'publishing')
        with self.assertRaises(Blocked):
            self._run('ref-401', script=script, propagate=True)
        self.assertEqual(script.models, 1)
        self.assertEqual(len(script.posts('/git/refs')), 1)
        self.assertEqual(CircuitBreaker(self.breaker_path).reason(), 'auth')

    def test_network_down_blocks_without_second_post(self):
        script = self._run('get-down')
        self.assertEqual(len(script.posts('/git/refs')), 1)
        self.assertEqual(script.posts('/pulls'), [])
        self.assertEqual(script.models, 1)
        row = Queue(self.db).fetch(1)
        self.assertEqual(row['state'], 'blocked')
        self.assertEqual(row['result'], 'publish_unreconciled')
        self.assertEqual(CircuitBreaker(self.breaker_path).reason(), 'unreconcilable_write')
        gets = [call for call in script.calls if call[0] == 'GET' and call[1].startswith('/git/ref/heads/codex/')]
        self.assertEqual(len(gets), 1)

    def test_publish_timeout_branches(self):
        absent = self._run('ref-timeout')
        self.assertEqual(len(absent.posts('/git/refs')), 1)
        self.assertEqual(absent.posts('/pulls'), [])
        self.assertEqual(Queue(self.db).fetch(1)['result'], 'publish_absent')
        self.assertFalse(self.breaker_path.exists())
        self.assertEqual(absent.models, 1)
        present_db = self.root / 'present.db'
        Queue(present_db).migrate_up()
        present = self._run('pull-timeout', database=present_db, breaker=self.root / 'present.breaker')
        self.assertEqual(len(present.posts('/pulls')), 1)
        self.assertEqual(len(present.posts('/git/refs')), 1)
        self.assertEqual(Queue(present_db).fetch(1)['state'], 'review')
        self.assertEqual(Queue(present_db).fetch(1)['published_url'], URL)
        self.assertEqual(Queue(present_db).fetch(1)['model_started'], 1)
        self.assertTrue(any(FEEDBACK_MARKER in body for body in present.comments))
        rejected = self.root / 'rejected.db'
        Queue(rejected).migrate_up()
        rejected_script = self._run('ref-422', database=rejected, breaker=self.root / 'rejected.breaker')
        self.assertEqual(len(rejected_script.posts('/git/refs')), 1)
        self.assertEqual(Queue(rejected).fetch(1)['result'], 'publish_absent')
        self.assertFalse((self.root / 'rejected.breaker').exists())
        clean_db = self.root / 'clean.db'
        Queue(clean_db).migrate_up()
        clean = self._run('ok', database=clean_db, breaker=self.root / 'clean.breaker')
        self.assertEqual(clean.models, 1)
        self.assertEqual(len(clean.posts('/git/refs')), 1)
        self.assertEqual(len(clean.posts('/pulls')), 1)
        self.assertEqual(Queue(clean_db).fetch(1)['state'], 'review')
        self.assertEqual(Queue(clean_db).fetch(1)['feedback_posts'], 1)
        self.assertFalse((self.root / 'clean.breaker').exists())

    def test_feedback_timeout_reposts_once(self):
        script = self._run('feedback-timeout')
        # One acceptance comment, one timed-out feedback POST, and one stored re-post.
        self.assertEqual(len(script.posts('/issues/12/comments')), 3)
        self.assertEqual(len(script.comments), 1)
        self.assertIn(FEEDBACK_MARKER, script.comments[0])
        self.assertEqual(Queue(self.db).fetch(1)['state'], 'review')
        self.assertEqual(Queue(self.db).fetch(1)['feedback_posts'], 2)
        self.assertEqual(script.models, 1)

    def test_breaker_latched_across_restart(self):
        breaker = CircuitBreaker(self.breaker_path)
        breaker.latch('auth')
        breaker.latch('policy')
        self.assertEqual(breaker.reason(), 'auth')
        restarted = CircuitBreaker(self.breaker_path)
        self.assertTrue(restarted.latched())
        self.assertEqual(restarted.reason(), 'auth')
        self.assertEqual(self.breaker_path.stat().st_mode & 0o777, 0o600)
        names = [name for name in dir(CircuitBreaker) if 'clear' in name or 'reset' in name or 'unlatch' in name]
        self.assertEqual(names, [])
        source = (ROOT / 'automation/publish_reconcile.py').read_text()
        self.assertNotIn('unlink', source)
        self.assertNotIn('.remove(', source)
        self.breaker_path.unlink()
        self.assertFalse(CircuitBreaker(self.breaker_path).latched())

    def test_duplicate_claim_latches(self):
        breaker = CircuitBreaker(self.breaker_path)
        queue = Queue(self.db, breaker=breaker)
        queue.activate(repo='example/fixture', issue=41, authorization_version='auth', trigger='trig',
                       day='2026-11-12', max_attempts=2, max_daily=3, now=NOW)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            queue.activate(repo='example/fixture', issue=41, authorization_version='auth', trigger='trig',
                           day='2026-11-12', max_attempts=2, max_daily=3, now=NOW)
        self.assertEqual(CircuitBreaker(self.breaker_path).reason(), 'duplicate_claim')
        self.assertEqual(Queue(self.db).fetch(1)['attempt'], 1)
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 0)
        with self.assertRaisesRegex(QueueBlocked, 'circuit breaker latched'):
            Queue(self.db, breaker=CircuitBreaker(self.breaker_path)).activate(
                repo='example/fixture', issue=42, authorization_version='auth', trigger='trig',
                day='2026-11-12', max_attempts=2, max_daily=3, now=NOW)

    def test_ledger_corruption_latches(self):
        original = self.db.read_bytes()
        broken = self.root / 'broken.db'
        broken.write_bytes(original[:80])
        frozen = broken.read_bytes()
        path = self.root / 'broken.db.breaker'
        with self.assertRaisesRegex(QueueBlocked, 'corrupt'):
            Queue(broken, breaker=CircuitBreaker(path)).reconcile()
        self.assertEqual(broken.read_bytes(), frozen)
        self.assertEqual(CircuitBreaker(path).reason(), 'ledger')
        self.assertEqual(list(self.root.glob('broken.db')), [broken])

    def test_safety_test_failure_latches(self):
        script = self._run('ok', bad_test=True)
        self.assertEqual(script.models, 1)
        self.assertEqual(script.posts('/git/refs'), [])
        self.assertEqual(script.posts('/pulls'), [])
        self.assertEqual(CircuitBreaker(self.breaker_path).reason(), 'safety_test')
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        with self.assertRaises(Blocked):
            self._run('ok', script=script, bad_test=True, propagate=True)
        self.assertEqual(script.models, 1)

    def test_policy_and_protection_drift_stop_before_model(self):
        policy = Script()
        policy.repo['allow_auto_merge'] = True
        self._run('ok', script=policy)
        self.assertEqual(policy.models, 0)
        self.assertEqual(policy.posts('/git/refs'), [])
        self.assertEqual(CircuitBreaker(self.breaker_path).reason(), 'policy')
        protected = self.root / 'protected.db'
        Queue(protected).migrate_up()
        guard = Script()
        guard.protected = False
        self._run('ok', script=guard, database=protected, breaker=self.root / 'protected.breaker')
        self.assertEqual(guard.models, 0)
        self.assertEqual(guard.posts('/pulls'), [])
        self.assertEqual(CircuitBreaker(self.root / 'protected.breaker').reason(), 'branch_protection')

    def test_feature_stays_off(self):
        settings = json.loads((ROOT / 'automation/settings.example.json').read_text())
        self.assertIs(settings['enabled'], False)
        self.assertEqual(settings['canary_issue'], 4)
        self.assertNotIn('publish_reconcile', settings)
        self.assertNotIn('task_queue', settings)
        digest = hashlib.sha256((ROOT / '.github/workflows/ci.yml').read_bytes()).hexdigest()
        self.assertEqual(digest, CI_SHA256)
        with patch('automation.dispatcher._enabled_publication', side_effect=AssertionError('reconcile used')):
            self._run_disabled({})
            self._run_disabled({'publish_reconcile': {'enabled': 'true'}})
            self._run_disabled({'publish_reconcile': {'enabled': False}})

    def _config(self, database=None, breaker=None, reconcile=True):
        config = {
            'allowed_actors': ['owner'],
            'max_attempts_per_issue': 2,
            'max_runs_per_day': 3,
            'retry_delay_seconds': 0,
            'timeout_seconds': 30,
            'test_timeout_seconds': 30,
            'total_timeout_seconds': 30,
            'task_queue': {
                'enabled': True,
                'database': str(database or self.db),
                'authorization_version': 'auth',
            },
        }
        if reconcile:
            config['publish_reconcile'] = {'enabled': True, 'breaker': str(breaker or self.breaker_path)}
        return config

    def _github(self, script):
        api = GitHub('synthetic-token')
        api.api = script.api
        api.pages = script.pages
        api.snapshot = lambda checkout: (SHA, SHA)
        return api

    def _run(self, mode, database=None, breaker=None, script=None, bad_test=False, propagate=False):
        script = script or Script()
        script.mode = mode
        database = database or self.db

        def fake_child(args, checkout, timeout, log, env, remote_stop=None, heartbeat=None):
            self.assertNotIn('GITHUB_TOKEN', env)
            if '--json' in args:
                script.models += 1
                (checkout / 'docs').mkdir()
                (checkout / 'docs/sample.md').write_text('SAMPLE MODE\n')
                log.write_text('SIMULATED MODEL; no inference')
            else:
                policy = json.loads((ROOT / 'automation/test_manifest.json').read_text())
                payload = {'success': not bad_test, 'count': len(policy['tests']), 'tests': sorted(policy['tests'])}
                log.write_text('SIMULATED TEST WORKER\nCF_TEST_RESULT ' + json.dumps(payload) + '\n')

        def fake_diff(checkout, paths):
            return [('docs/sample.md', (checkout / 'docs/sample.md').read_bytes(), '100644')]

        with tempfile.TemporaryDirectory() as temp, sqlite3.connect(str(Path(temp) / 'runs.db')) as db:
            root = Path(temp)
            (root / 'codex-home').mkdir()
            (root / 'codex-home/auth.json').write_text('SYNTHETIC PRESENCE FIXTURE')
            db.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
            api = self._github(script)
            with patch('automation.dispatcher.RUNTIME', root), patch('automation.dispatcher.preflight'), \
                    patch('automation.dispatcher.child', side_effect=fake_child), \
                    patch('automation.dispatcher.prepare'), patch('automation.dispatcher.diff', side_effect=fake_diff):
                try:
                    run_issue(api, test_automation.issue(), self._config(database, breaker), db)
                except Blocked:
                    if propagate:
                        raise
        return script

    def _run_disabled(self, extra):
        database = self.root / f'off-{len(list(self.root.glob("off-*.db")))}.db'
        Queue(database).migrate_up()
        class FakeAPI:
            deadline = None
            def __init__(self):
                self.publications = []
                self.feedbacks = []
            def pages(self, route):
                if '/events' in route:
                    return [EVENT]
                return []
            def api(self, method, route, data=None):
                if route == '/labels/codex-stop':
                    return {'name': 'codex-stop'}
                return test_automation.issue()
            def snapshot(self, checkout):
                (checkout / 'README.md').write_text('Trusted synthetic base')
                return SHA, SHA
            def publish(self, *args, record=None):
                self.publications.append(args)
                if record:
                    record(URL)
                return URL
            def feedback(self, number, message):
                self.feedbacks.append(message)

        def fake_child(args, checkout, timeout, log, env, remote_stop=None, heartbeat=None):
            if '--json' in args:
                (checkout / 'docs').mkdir()
                (checkout / 'docs/sample.md').write_text('SAMPLE MODE\n')
                log.write_text('SIMULATED MODEL; no inference')
            else:
                policy = json.loads((ROOT / 'automation/test_manifest.json').read_text())
                log.write_text('SIMULATED TEST WORKER\nCF_TEST_RESULT ' + json.dumps(
                    {'success': True, 'count': len(policy['tests']), 'tests': sorted(policy['tests'])}) + '\n')

        def fake_diff(checkout, paths):
            return [('docs/sample.md', (checkout / 'docs/sample.md').read_bytes(), '100644')]

        config = self._config(database=database, reconcile=False)
        config.update(extra)
        with tempfile.TemporaryDirectory() as temp, sqlite3.connect(str(Path(temp) / 'runs.db')) as db:
            root = Path(temp)
            (root / 'codex-home').mkdir()
            (root / 'codex-home/auth.json').write_text('SYNTHETIC PRESENCE FIXTURE')
            db.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
            with patch('automation.dispatcher.RUNTIME', root), patch('automation.dispatcher.preflight'), \
                    patch('automation.dispatcher.child', side_effect=fake_child), \
                    patch('automation.dispatcher.prepare'), patch('automation.dispatcher.diff', side_effect=fake_diff):
                run_issue(FakeAPI(), test_automation.issue(), config, db)
        self.assertEqual(Queue(database).fetch(1)['state'], 'review')


MARKER_COMMENT = '<!-- cf-codex-worker -->\n' + FEEDBACK_MARKER + '\nDraft PR: ' + URL


if __name__ == '__main__':
    unittest.main()
