"""Queue, claim, lease, and fencing. Fixture databases only; no network or model."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import test_automation
from automation.dispatcher import ROOT, Blocked, run_issue
from automation.task_queue import Hold, Queue, QueueBlocked, QueueFenced


NOW = 1_700_000_000_000
LEASE = 120_000
DAY = '2026-11-12'
REPO_KEY = 'example/fixture'
CI_SHA256 = '4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d'
STAGES = (
    'queued', 'claimed', 'snapshot', 'model', 'testing', 'publishing',
    'feedback_pending', 'review', 'blocked', 'stopped', 'interrupted',
)
FORWARD = ('snapshot', 'model', 'testing', 'publishing', 'feedback_pending', 'review')


def queue(path):
    return Queue(path)


def activate(q, trigger='trig', issue=41, now=NOW, max_attempts=2, prior_attempts=0):
    return q.activate(repo=REPO_KEY, issue=issue, authorization_version='auth', trigger=trigger,
                      day=DAY, max_attempts=max_attempts, max_daily=3, prior_attempts=prior_attempts, now=now)


def enqueue(q, trigger='trig', issue=41, now=NOW):
    return q.enqueue(repo=REPO_KEY, issue=issue, authorization_version='auth', trigger=trigger,
                     day=DAY, max_attempts=2, max_daily=3, now=now)


def claim(q, trigger='trig', issue=41, now=NOW):
    return q.claim(repo=REPO_KEY, issue=issue, authorization_version='auth', trigger=trigger, now=now)


def export_legacy(path):
    uri = 'file:' + Path(path).resolve().as_posix() + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    try:
        chunks = []
        for name in ('runs', 'notices'):
            master = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            chunks.append(b'TABLE ' + name.encode() + b'\n' + (master[0] or '').encode() + b'\n')
            cols = [row[1] for row in conn.execute(f'PRAGMA table_info({name})')]
            quoted = ', '.join(f'quote("{col}")' for col in cols)
            order = ', '.join(f'"{col}"' for col in cols)
            for row in conn.execute(f'SELECT {quoted} FROM "{name}" ORDER BY {order}'):
                chunks.append(b'ROW ' + name.encode() + b' ' + '|'.join(row).encode() + b'\n')
        return b''.join(chunks)
    finally:
        conn.close()


def legacy_names(path):
    conn = sqlite3.connect(f'file:{Path(path).resolve().as_posix()}?mode=ro', uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    finally:
        conn.close()


WORKER = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from automation.task_queue import Queue, QueueError
mode, database, ready, go = sys.argv[2:]
open(ready, "w").close()
deadline = time.time() + 5
while not os.path.exists(go):
    if time.time() > deadline:
        raise SystemExit(2)
    time.sleep(0.01)
q = Queue(database)
try:
    if mode == "activate":
        hold = q.activate(repo="example/fixture", issue=41, authorization_version="auth",
            trigger="trig", day="2026-11-12", max_attempts=2, max_daily=3, now=1700000000000)
    else:
        hold = q.claim(repo="example/fixture", issue=42, authorization_version="auth",
            trigger="trig", now=1700000000000)
    print(json.dumps({"ok": True, "token": hold.token, "attempt": hold.attempt}))
except QueueError as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__}))
'''


class QueueTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / 'queue.db'
        queue(self.db).migrate_up()

    def tearDown(self):
        self._tmp.cleanup()

    def test_duplicate_claim_rejected(self):
        q = queue(self.db)
        enqueue(q)
        first = claim(q)
        self.assertEqual(first.token, 1)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            claim(q)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            enqueue(q)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            activate(q)
        other = queue(self.root / 'second.db')
        other.migrate_up()
        activate(other)
        before = len(other.audit_export())
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            activate(other)
        self.assertEqual(len(other.audit_export()), before)
        self.assertEqual(other.fetch(1)['attempt'], 1)
        self.assertEqual(other.fetch(1)['model_started'], 0)

    def test_two_processes_cannot_both_claim(self):
        worker = self.root / 'worker.py'
        worker.write_text(WORKER)
        env = {'PATH': os.environ['PATH'], 'PYTHONPATH': str(ROOT), 'HOME': str(self.root),
               'TMPDIR': str(self.root), 'LANG': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}
        enqueue(queue(self.db), issue=42)
        claimed = self._race(worker, env, self.db, 'claim')
        self.assertEqual(sum(1 for item in claimed if item['ok']), 1)
        self.assertEqual(queue(self.db).fetch(1)['state'], 'claimed')
        self.assertEqual(queue(self.db).fetch(1)['model_started'], 0)
        fresh = self.root / 'fresh.db'
        queue(fresh).migrate_up()
        activated = self._race(worker, env, fresh, 'activate')
        self.assertEqual(sum(1 for item in activated if item['ok']), 1)
        conn = sqlite3.connect(fresh)
        try:
            self.assertEqual(conn.execute('SELECT count(*) FROM cf_task_queue_v1').fetchone()[0], 1)
        finally:
            conn.close()

    def _race(self, worker, env, database, mode):
        procs = []
        try:
            for name in ('a', 'b'):
                procs.append(subprocess.Popen(
                    [sys.executable, str(worker), str(ROOT), mode, str(database),
                     str(self.root / f'{mode}-{name}.ready'), str(self.root / f'{mode}.go')],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self.root,
                    start_new_session=True))
            deadline = time.time() + 5
            while time.time() < deadline:
                if all((self.root / f'{mode}-{name}.ready').exists() for name in ('a', 'b')):
                    break
                time.sleep(0.01)
            else:
                self.fail('workers did not reach the barrier')
            (self.root / f'{mode}.go').write_text('go')
            results = []
            for proc in procs:
                out, err = proc.communicate(timeout=10)
                self.assertEqual(proc.returncode, 0, err.decode())
                results.append(json.loads(out.decode()))
            return results
        finally:
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()

    def test_kill_at_each_stage_does_not_rerun_or_refund(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                path = self.root / f'{stage}.db'
                q = queue(path)
                q.migrate_up()
                started = 1 if stage in FORWARD[1:] else 0
                hold = self._reach(q, stage)
                task_id = 1
                before = q.fetch(task_id)
                self.assertEqual(before['model_started'], started)
                self.assertEqual(before['attempt'], 1)
                audit = q.audit_export()
                self.assertTrue(audit)
                restarted = queue(path)
                self.assertEqual(restarted.audit_export(), audit)
                with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
                    activate(restarted, now=NOW)
                self.assertEqual(restarted.fetch(task_id)['model_started'], started)
                self.assertEqual(restarted.fetch(task_id)['attempt'], 1)
                self.assertEqual(restarted.audit_export(), audit)
                restarted.reconcile(now=NOW + LEASE)
                after = restarted.fetch(task_id)
                if stage in ('review', 'blocked', 'stopped', 'interrupted'):
                    self.assertEqual(after['state'], stage)
                else:
                    self.assertEqual(after['state'], 'interrupted')
                self.assertEqual(after['model_started'], started)
                self.assertEqual(after['attempt'], 1)
                self.assertEqual(restarted.audit_export()[:len(audit)], audit)
                with self.assertRaises(QueueBlocked):
                    activate(restarted, now=NOW + LEASE)
                self.assertEqual(restarted.fetch(task_id)['model_started'], started)
                if hold is not None and stage == 'publishing':
                    calls = []
                    with self.assertRaises(QueueFenced):
                        hold.publish(lambda: calls.append('x') or 'https://example.invalid/simulated', now=NOW + LEASE)
                    self.assertEqual(calls, [])

    def _reach(self, q, stage):
        if stage == 'queued':
            enqueue(q)
            return None
        hold = activate(q)
        if stage == 'claimed':
            return hold
        if stage == 'blocked':
            return hold.close_as('blocked', now=NOW)
        if stage == 'stopped':
            return hold.close_as('stopped', now=NOW)
        if stage == 'interrupted':
            q.reconcile(now=NOW + LEASE)
            return hold
        for name in FORWARD:
            hold.advance(name, now=NOW)
            if name == stage:
                return hold
        self.fail(stage)

    def test_stale_holder_publish_rejected_by_fencing(self):
        q = queue(self.db)
        hold = self._reach(q, 'publishing')
        calls = []
        forged = Hold(q, hold.task_id, hold.owner, hold.token + 1, hold.attempt)
        with self.assertRaisesRegex(QueueFenced, 'fencing token rejected'):
            forged.publish(lambda: calls.append('forged') or 'https://example.invalid/forged', now=NOW)
        stranger = Hold(q, hold.task_id, 'other-owner', hold.token, hold.attempt)
        with self.assertRaisesRegex(QueueFenced, 'fencing token rejected'):
            stranger.publish(lambda: calls.append('stranger') or 'https://example.invalid/stranger', now=NOW)
        self.assertEqual(calls, [])
        self.assertEqual(q.fetch(hold.task_id)['state'], 'publishing')
        self.assertEqual(q.fetch(hold.task_id)['fencing_token'], hold.token)
        url = hold.publish(lambda: calls.append('live') or 'https://example.invalid/simulated', now=NOW)
        self.assertEqual(calls, ['live'])
        self.assertEqual(url, 'https://example.invalid/simulated')
        self.assertEqual(q.fetch(hold.task_id)['state'], 'feedback_pending')
        q.reconcile(now=NOW + LEASE)
        stale = []
        with self.assertRaises(QueueFenced):
            hold.publish(lambda: stale.append('stale') or 'https://example.invalid/stale', now=NOW + LEASE)
        self.assertEqual(stale, [])
        row = q.fetch(hold.task_id)
        self.assertEqual(row['state'], 'interrupted')
        self.assertGreater(row['fencing_token'], hold.token)
        self.assertEqual(row['model_started'], 1)
        self.assertEqual(row['published_url'], 'https://example.invalid/simulated')

    def test_lease_expiry_is_interrupted_not_rerun(self):
        q = queue(self.db)
        hold = activate(q)
        with self.assertRaisesRegex(QueueFenced, 'lease expired'):
            hold.heartbeat(now=NOW + LEASE)
        row = q.fetch(hold.task_id)
        self.assertEqual(row['state'], 'interrupted')
        self.assertEqual(row['attempt'], 1)
        self.assertEqual(row['model_started'], 0)
        self.assertGreater(row['fencing_token'], hold.token)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            activate(q, now=NOW + LEASE)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            claim(q, now=NOW + LEASE)
        self.assertEqual(q.fetch(hold.task_id)['state'], 'interrupted')
        self.assertEqual(q.fetch(hold.task_id)['model_started'], 0)

    def test_heartbeat_extends_lease_without_changing_token(self):
        q = queue(self.db)
        hold = activate(q)
        hold.heartbeat(now=NOW + 30_000)
        row = q.fetch(hold.task_id)
        self.assertEqual(row['fencing_token'], hold.token)
        self.assertEqual(row['state'], 'claimed')
        self.assertEqual(row['lease_until'], NOW + 30_000 + LEASE)
        self.assertEqual(row['model_started'], 0)
        self.assertEqual(Queue(self.db).heartbeat_ms, 30_000)
        self.assertEqual(Queue(self.db).lease_ms, LEASE)

    def test_corrupted_database_fails_closed_without_reset(self):
        missing = self.root / 'missing.db'
        with self.assertRaisesRegex(QueueBlocked, 'missing'):
            queue(missing).reconcile()
        self.assertFalse(missing.exists())
        garbage = self.root / 'garbage.db'
        blob = b'not a database file'
        garbage.write_bytes(blob)
        with self.assertRaisesRegex(QueueBlocked, 'corrupt'):
            queue(garbage).activate(repo=REPO_KEY, issue=1, authorization_version='auth', trigger='trig',
                                    day=DAY, max_attempts=2, max_daily=3, now=NOW)
        self.assertEqual(garbage.read_bytes(), blob)
        self.assertEqual(list(self.root.glob('garbage.db*')), [garbage])
        broken = self.root / 'broken.db'
        queue(broken).migrate_up()
        broken.write_bytes(broken.read_bytes()[:80])
        frozen = broken.read_bytes()
        with self.assertRaisesRegex(QueueBlocked, 'corrupt'):
            queue(broken).reconcile()
        self.assertEqual(broken.read_bytes(), frozen)
        with self.assertRaisesRegex(QueueBlocked, 'legacy ledger'):
            Queue(self.root / 'state.db')

    def test_unknown_state_fails_closed(self):
        conn = sqlite3.connect(self.db)
        conn.execute(
            '''INSERT INTO cf_task_queue_v1 (
                repo, issue, authorization_version, trigger_key, state, attempt, fencing_token,
                owner_hash, lease_until, reserved_at, heartbeat_at, day, model_started, published_url, result
            ) VALUES (?,?,?,?, 'mystery', 1, 4, NULL, ?, ?, NULL, ?, 0, NULL, NULL)''',
            (REPO_KEY, 41, 'auth', 'trig', NOW + LEASE, NOW, DAY))
        conn.commit()
        conn.close()
        q = queue(self.db)
        self.assertEqual(q.effective_state(1), 'blocked')
        self.assertEqual(q.fetch(1)['state'], 'mystery')
        with self.assertRaises(QueueBlocked):
            activate(q)
        q.reconcile(now=NOW)
        row = q.fetch(1)
        self.assertEqual(row['state'], 'blocked')
        self.assertEqual(row['attempt'], 1)
        self.assertEqual(row['model_started'], 0)
        self.assertGreater(row['fencing_token'], 4)
        self.assertIn('unknown_state', {item[2] for item in q.audit_export()})
        with self.assertRaises(QueueBlocked):
            activate(q, now=NOW)

    def test_migration_up_down_preserves_legacy_rows(self):
        path = self.root / 'fixture.db'
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
        conn.execute('CREATE TABLE notices(issue INTEGER, key TEXT, PRIMARY KEY(issue, key))')
        conn.execute('INSERT INTO runs VALUES (7, 4, ?, ?, ?, ?, ?)', ("lab'el", 'blocked', 1.5, '2026-11-07', 'synthetic'))
        conn.execute('INSERT INTO runs VALUES (11, 4, ?, ?, ?, ?, NULL)', ('label-200', 'pr', 2.25, '2026-11-07'))
        conn.execute('INSERT INTO notices VALUES (4, ?)', ('sample-key',))
        conn.commit()
        conn.close()
        original_names = legacy_names(path)
        before = export_legacy(path)
        q = queue(path)
        q.migrate_up()
        self.assertEqual(export_legacy(path), before)
        activate(q, now=NOW)
        self.assertEqual(export_legacy(path), before)
        with self.assertRaisesRegex(QueueBlocked, 'already applied'):
            q.migrate_up()
        self.assertEqual(export_legacy(path), before)
        q.migrate_down()
        self.assertEqual(export_legacy(path), before)
        self.assertEqual(legacy_names(path), original_names)
        conn = sqlite3.connect(path)
        try:
            ids = [row[0] for row in conn.execute('SELECT id FROM runs ORDER BY id')]
            self.assertEqual(ids, [7, 11])
            self.assertIsNone(conn.execute("SELECT result FROM runs WHERE id=11").fetchone()[0])
        finally:
            conn.close()
        q.migrate_up()
        self.assertEqual(export_legacy(path), before)
        empty = self.root / 'empty.db'
        sqlite3.connect(empty).close()
        with self.assertRaisesRegex(QueueBlocked, 'schema mismatch'):
            queue(empty).migrate_down()

    def test_reservation_persisted_before_model_and_not_refunded(self):
        q = queue(self.db)
        calls = []
        hold = activate(q)
        row = q.fetch(hold.task_id)
        self.assertEqual(row['state'], 'claimed')
        self.assertEqual(row['model_started'], 0)
        self.assertEqual(row['attempt'], 1)
        self.assertEqual(calls, [])
        restarted = queue(self.db)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            activate(restarted)
        self.assertEqual(calls, [])
        self.assertEqual(restarted.fetch(hold.task_id)['model_started'], 0)
        hold.advance('snapshot', now=NOW)
        hold.advance('model', now=NOW)
        self.assertEqual(q.fetch(hold.task_id)['model_started'], 1)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE cf_task_queue_v1 SET state='snapshot'")
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(QueueBlocked, 'model already started'):
            hold.advance('model', now=NOW)
        self.assertEqual(q.fetch(hold.task_id)['model_started'], 1)
        hold.close_as('blocked', now=NOW)
        self.assertEqual(q.fetch(hold.task_id)['state'], 'blocked')
        self.assertEqual(q.fetch(hold.task_id)['attempt'], 1)
        with self.assertRaisesRegex(QueueBlocked, 'attempt budget exhausted'):
            activate(q, trigger='other', max_attempts=1, now=NOW + 1)
        counted = sqlite3.connect(self.db)
        try:
            self.assertEqual(counted.execute('SELECT count(*) FROM cf_task_queue_v1').fetchone()[0], 1)
        finally:
            counted.close()

    def test_clock_backwards_fails_closed(self):
        q = queue(self.db)
        hold = activate(q, now=5_000)
        with self.assertRaisesRegex(QueueBlocked, 'clock moved backwards'):
            hold.heartbeat(now=4_999)
        row = q.fetch(hold.task_id)
        self.assertEqual(row['state'], 'blocked')
        self.assertEqual(row['model_started'], 0)
        self.assertEqual(row['attempt'], 1)
        with self.assertRaises(QueueBlocked):
            activate(q, now=4_999)

    def test_schema_mismatch_does_not_auto_migrate(self):
        plain = self.root / 'plain.db'
        conn = sqlite3.connect(plain)
        conn.execute('PRAGMA user_version=0')
        conn.commit()
        conn.close()
        before = plain.read_bytes()
        with self.assertRaisesRegex(QueueBlocked, 'schema mismatch'):
            queue(plain).reconcile()
        self.assertEqual(plain.read_bytes(), before)
        names = legacy_names(plain)
        self.assertNotIn('cf_task_queue_v1', names)
        self.assertNotIn('cf_schema_migration', names)

    def test_unconfigured_dispatcher_matches_current_behavior(self):
        with patch('automation.task_queue.Queue.activate', side_effect=AssertionError('queue used')):
            test_automation.AutomationTest('test_simulated_issue_model_tests_pr_feedback').pipeline()
        disabled = {'task_queue': {'enabled': False, 'database': str(self.db)}}
        with patch('automation.task_queue.Queue.activate', side_effect=AssertionError('queue used')):
            self._run_dispatcher(disabled, model=lambda: None)
        counted = sqlite3.connect(self.db)
        try:
            self.assertEqual(counted.execute('SELECT count(*) FROM cf_task_queue_v1').fetchone()[0], 0)
        finally:
            counted.close()

    def test_configured_dispatcher_reserves_before_model(self):
        seen = {}
        def model():
            conn = sqlite3.connect(self.db)
            try:
                row = conn.execute('SELECT state, model_started, attempt FROM cf_task_queue_v1').fetchone()
            finally:
                conn.close()
            seen['row'] = row
        self._run_dispatcher(self._spec(), model=model)
        self.assertEqual(seen['row'], ('model', 1, 1))
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute('SELECT state FROM cf_task_queue_v1').fetchone()[0], 'review')
        finally:
            conn.close()

    def test_dispatcher_stale_fence_blocks_publish(self):
        calls = {'model': 0, 'publish': 0}
        def model():
            calls['model'] += 1
            conn = sqlite3.connect(self.db)
            try:
                conn.execute('UPDATE cf_task_queue_v1 SET fencing_token = fencing_token + 1')
                conn.commit()
            finally:
                conn.close()
        with self.assertRaises(Blocked):
            self._run_dispatcher(self._spec(), model=model, publish=lambda: calls.__setitem__('publish', calls['publish'] + 1))
        self.assertEqual(calls, {'model': 1, 'publish': 0})
        conn = sqlite3.connect(self.db)
        try:
            state, started = conn.execute('SELECT state, model_started FROM cf_task_queue_v1').fetchone()
        finally:
            conn.close()
        self.assertEqual(started, 1)
        self.assertNotEqual(state, 'queued')
        with self.assertRaises(Blocked):
            self._run_dispatcher(self._spec(), model=lambda: calls.__setitem__('model', calls['model'] + 1))
        self.assertEqual(calls['model'], 1)

    def test_example_settings_leave_queue_unconfigured(self):
        settings = json.loads((ROOT / 'automation/settings.example.json').read_text())
        self.assertIs(settings['enabled'], False)
        self.assertEqual(settings['canary_issue'], 4)
        self.assertNotIn('task_queue', settings)
        digest = hashlib.sha256((ROOT / '.github/workflows/ci.yml').read_bytes()).hexdigest()
        self.assertEqual(digest, CI_SHA256)

    def _spec(self):
        return {'task_queue': {'enabled': True, 'database': str(self.db)}}

    def _run_dispatcher(self, extra, model, publish=None):
        class FakeAPI:
            deadline = None
            def __init__(self):
                self.feedbacks = []
                self.publications = []
            def pages(self, route):
                if '/events' in route:
                    return [{'id': 9, 'event': 'labeled', 'label': {'name': 'codex-ready'}, 'actor': {'login': 'owner'}}]
                return []
            def api(self, method, route, data=None):
                if route == '/labels/codex-stop':
                    return {'name': 'codex-stop'}
                return test_automation.issue()
            def snapshot(self, checkout):
                (checkout / 'README.md').write_text('Trusted synthetic base')
                return 'a' * 40, 'b' * 40
            def publish(self, *args, record=None):
                if publish is not None:
                    publish()
                self.publications.append(args)
                url = 'https://example.invalid/SIMULATED-PR'
                if record:
                    record(url)
                return url
            def feedback(self, number, message):
                self.feedbacks.append(message)
        def fake_child(args, checkout, timeout, log, env, remote_stop=None, heartbeat=None):
            self.assertNotIn('GITHUB_TOKEN', env)
            if '--json' in args:
                model()
                (checkout / 'docs').mkdir()
                (checkout / 'docs/sample.md').write_text('SAMPLE MODE\n')
                log.write_text('SIMULATED MODEL; no inference')
            else:
                policy = json.loads((ROOT / 'automation/test_manifest.json').read_text())
                log.write_text('SIMULATED TEST WORKER\nCF_TEST_RESULT ' + json.dumps(
                    {'success': True, 'count': len(policy['tests']), 'tests': sorted(policy['tests'])}) + '\n')
        def fake_diff(checkout, paths):
            return [('docs/sample.md', (checkout / 'docs/sample.md').read_bytes(), '100644')]
        with tempfile.TemporaryDirectory() as temp, sqlite3.connect(str(Path(temp) / 'runs.db')) as db:
            root = Path(temp)
            (root / 'codex-home').mkdir()
            (root / 'codex-home/auth.json').write_text('SYNTHETIC PRESENCE FIXTURE')
            db.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
            api = FakeAPI()
            config = {'allowed_actors': ['owner'], 'max_attempts_per_issue': 2, 'max_runs_per_day': 3,
                      'retry_delay_seconds': 0, 'timeout_seconds': 30, 'test_timeout_seconds': 30}
            config.update(extra)
            with patch('automation.dispatcher.RUNTIME', root), patch('automation.dispatcher.preflight'), \
                    patch('automation.dispatcher.child', side_effect=fake_child), \
                    patch('automation.dispatcher.prepare'), patch('automation.dispatcher.diff', side_effect=fake_diff):
                run_issue(api, test_automation.issue(), config, db)
            return api, db


if __name__ == '__main__':
    unittest.main()
