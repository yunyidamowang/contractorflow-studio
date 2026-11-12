"""P1 acceptance fixtures. Simulated process death and HTTP only.

No real ledger, model, socket, or launchd install. A file named state.db is
used only when the ledger-proof fixture flag is set, and only inside this
temporary directory.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import test_automation
import test_publish_reconcile
from automation.dispatcher import REPO, ROOT, Blocked, recover_open, run_issue
from automation.launchd_sample import main as launchd_main
from automation.ledger_proof import LedgerProofError, prove_legacy_rows
from automation.publish_reconcile import FEEDBACK_MARKER, CircuitBreaker
from automation.task_queue import (
    Hold, Queue, QueueBlocked, QueueFenced, _chain_hash,
)


NOW = 1_700_000_000_000
LEASE = 120_000
DAY = '2026-11-12'
SHA = 'a' * 40
URL = 'https://example.invalid/pull/1'
CI_SHA256 = '4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d'
REPO_KEY = 'example/fixture'
STAGES = (
    'queued', 'claimed', 'snapshot', 'model', 'testing', 'publishing',
    'publish_unknown', 'feedback_pending', 'review', 'blocked', 'stopped',
    'interrupted',
)
MODEL_STAGES = frozenset({
    'model', 'testing', 'publishing', 'publish_unknown', 'feedback_pending', 'review',
})
KILL_WORKER = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from automation.task_queue import Queue
stage, database = sys.argv[2], sys.argv[3]
NOW = 1700000000000
LEASE = 120000
SHA = "a" * 40
q = Queue(database, audit=True)
def act():
    return q.activate(repo="example/fixture", issue=41, authorization_version="auth", trigger="trig",
        day="2026-11-12", max_attempts=2, max_daily=3, now=NOW)
if stage == "queued":
    q.enqueue(repo="example/fixture", issue=41, authorization_version="auth", trigger="trig",
        day="2026-11-12", max_attempts=2, max_daily=3, now=NOW)
elif stage == "claimed":
    act()
elif stage == "blocked":
    act().close_as("blocked", now=NOW)
elif stage == "stopped":
    act().close_as("stopped", now=NOW)
elif stage == "interrupted":
    act()
    q.reconcile(now=NOW + LEASE)
elif stage == "publish_unknown":
    hold = act()
    for name in ("snapshot", "model", "testing", "publishing"):
        hold.advance(name, now=NOW)
    hold.note_publish_target("codex/issue-41-attempt-1-99", SHA, now=NOW)
    hold.mark_publish_unknown(now=NOW)
else:
    hold = act()
    for name in ("snapshot", "model", "testing", "publishing", "feedback_pending", "review"):
        hold.advance(name, now=NOW)
        if name == stage:
            break
    else:
        raise SystemExit("unknown stage")
print("READY", flush=True)
time.sleep(30)
'''
RACE_WORKER = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from automation.task_queue import Queue, QueueError
database, ready, go = sys.argv[2:]
open(ready, "w").close()
deadline = time.time() + 5
while not os.path.exists(go):
    if time.time() > deadline:
        raise SystemExit(2)
    time.sleep(0.01)
q = Queue(database, audit=True)
try:
    hold = q.activate(repo="example/fixture", issue=41, authorization_version="auth", trigger="trig",
        day="2026-11-12", max_attempts=2, max_daily=3, now=1700000000000)
    print(json.dumps({"ok": True, "token": hold.token}))
except QueueError as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__}))
'''


def activate(path, issue=41, trigger='trig', now=NOW):
    return Queue(path, audit=True).activate(
        repo=REPO_KEY, issue=issue, authorization_version='auth', trigger=trigger,
        day=DAY, max_attempts=2, max_daily=3, now=now)


def chain_of(path):
    return Queue(path, audit=True).verify_export()


def assert_chain(test, path, report=None):
    report = chain_of(path) if report is None else report
    test.assertTrue(report['ok'], report)
    test.assertIsNone(report['kind'])
    records = report['records']
    test.assertEqual([row['seq'] for row in records], list(range(1, len(records) + 1)))
    blob = json.dumps(report)
    for banned in ('@', 'https://', 'ghp_', 'github_pat_', 'Bearer', 'token='):
        test.assertNotIn(banned, blob)
    audit = Queue(path, audit=True).audit_export()
    states = [row['state'] for row in records]
    cursor = 0
    for item in audit:
        state = item[3]
        while cursor < len(states) and states[cursor] != state:
            cursor += 1
        test.assertLess(cursor, len(states), item)
        cursor += 1
    return report


class P1AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / 'queue.db'
        Queue(self.db).migrate_up()

    def tearDown(self):
        self._tmp.cleanup()

    def test_chain_export_is_redacted_and_linked(self):
        hold = activate(self.db)
        secret = hold.owner
        hold.heartbeat(now=NOW + 1_000)
        for name in ('snapshot', 'model', 'testing', 'publishing'):
            hold.advance(name, now=NOW + 1_000)
        calls = []
        forged = Hold(hold.queue, hold.task_id, secret, hold.token + 1, hold.attempt)
        with self.assertRaises(QueueFenced):
            forged.publish(lambda: calls.append(URL) or URL, now=NOW + 1_000)
        self.assertEqual(calls, [])
        hold.note_publish_target('codex/issue-41-attempt-1-99', SHA, now=NOW + 1_000)
        hold.mark_publish_unknown(now=NOW + 1_000)
        Queue(self.db, audit=True).apply_reconciliation(hold.task_id, 'exists', url=URL, now=NOW + 1_000)
        count = Queue(self.db, audit=True).begin_feedback_post(hold.task_id, now=NOW + 1_000)
        self.assertEqual(count, 1)
        Queue(self.db, audit=True).reconcile(now=NOW + 1_000 + LEASE)
        report = assert_chain(self, self.db)
        events = {row['event'] for row in report['records']}
        for name in ('claim', 'lease_renew', 'lease_expire', 'fencing_reject', 'state',
                     'publish_unknown', 'reconcile_result', 'feedback_retry'):
            self.assertIn(name, events)
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn(URL, json.dumps(report))
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        self.assertEqual(Queue(self.db).fetch(1)['attempt'], 1)
        self.assertEqual(calls, [])

    def test_chain_reports_tamper_deletion_reorder_and_truncation(self):
        self._seed_three()
        cases = (
            ('tamper', self._tamper),
            ('deletion', self._delete_middle),
            ('reorder', self._reorder),
            ('truncation', self._truncate),
        )
        for kind, mutate in cases:
            with self.subTest(kind=kind):
                path = self.root / f'{kind}.db'
                self._copy_db(path)
                mutate(path)
                report = chain_of(path)
                self.assertFalse(report['ok'])
                self.assertEqual(report['kind'], kind)
                self.assertEqual(report['seq'], 2 if kind != 'truncation' else 3)
                self.assertEqual(report['records'], [])
                self.assertNotIn('person@example.com', json.dumps(report))

    def test_open_failed_chain_fails_closed(self):
        self._seed_three()
        self._tamper(self.db)
        before = self.db.read_bytes()
        with self.assertRaisesRegex(QueueBlocked, 'audit chain failed'):
            Queue(self.db, audit=True).fetch(1)
        self.assertEqual(self.db.read_bytes(), before)
        report = chain_of(self.db)
        self.assertEqual((report['ok'], report['kind'], report['seq']), (False, 'tamper', 2))
        with self.assertRaisesRegex(QueueBlocked, 'audit chain failed'):
            activate(self.db, trigger='other')

    def test_duplicate_claim_does_not_start_twice(self):
        hold = activate(self.db)
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            activate(self.db)
        row = Queue(self.db).fetch(hold.task_id)
        self.assertEqual(row['attempt'], 1)
        self.assertEqual(row['model_started'], 0)
        self.assertEqual(row['state'], 'claimed')
        report = assert_chain(self, self.db)
        self.assertEqual(
            [item['detail'] for item in report['records'] if item['event'] == 'claim'],
            ['attempt_reserved', 'duplicate_rejected'])
        self.assertEqual(self._pr_count(self.db), 0)

    def test_two_processes_one_claim(self):
        worker = self.root / 'race.py'
        worker.write_text(RACE_WORKER)
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(self.root), 'TMPDIR': str(self.root),
               'LANG': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}
        procs = []
        try:
            for name in ('a', 'b'):
                procs.append(subprocess.Popen(
                    [sys.executable, str(worker), str(ROOT), str(self.db),
                     str(self.root / f'{name}.ready'), str(self.root / 'go')],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self.root,
                    start_new_session=True))
            deadline = time.time() + 5
            while time.time() < deadline and not all((self.root / f'{name}.ready').exists() for name in ('a', 'b')):
                time.sleep(0.01)
            else:
                if not all((self.root / f'{name}.ready').exists() for name in ('a', 'b')):
                    self.fail('workers did not reach the barrier')
            (self.root / 'go').write_text('go')
            results = []
            for proc in procs:
                out, err = proc.communicate(timeout=10)
                self.assertEqual(proc.returncode, 0, err.decode())
                results.append(json.loads(out.decode()))
        finally:
            for proc in procs:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
        self.assertEqual(sum(1 for item in results if item['ok']), 1)
        row = Queue(self.db).fetch(1)
        self.assertEqual(row['state'], 'claimed')
        self.assertEqual(row['model_started'], 0)
        self.assertEqual(row['attempt'], 1)
        report = assert_chain(self, self.db)
        self.assertEqual(sum(1 for item in report['records'] if item['detail'] == 'attempt_reserved'), 1)
        self.assertEqual(self._pr_count(self.db), 0)

    def test_power_loss_at_each_stage(self):
        worker = self.root / 'kill.py'
        worker.write_text(KILL_WORKER)
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(self.root), 'TMPDIR': str(self.root),
               'LANG': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}
        for stage in STAGES:
            with self.subTest(stage=stage):
                path = self.root / f'{stage}.db'
                Queue(path).migrate_up()
                proc = subprocess.Popen(
                    [sys.executable, str(worker), str(ROOT), stage, str(path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self.root,
                    start_new_session=True)
                try:
                    line = proc.stdout.readline()
                    if line != b'READY\n':
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                        err = proc.stderr.read().decode()
                        self.fail(err or repr(line))
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                    proc.stdout.close()
                    proc.stderr.close()
                started = 1 if stage in MODEL_STAGES else 0
                row = Queue(path).fetch(1)
                self.assertEqual(row['model_started'], started)
                self.assertEqual(row['attempt'], 1)
                self.assertIsNone(row['published_url'])
                before = len(chain_of(path)['records'])
                with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
                    activate(path)
                row = Queue(path).fetch(1)
                self.assertEqual(row['model_started'], started)
                self.assertEqual(row['attempt'], 1)
                report = assert_chain(self, path)
                self.assertGreater(len(report['records']), before)
                self.assertEqual(self._pr_count(path), 0)

    def test_crash_between_publish_and_feedback(self):
        now = time.time_ns() // 1_000_000
        hold = activate(self.db, issue=12, now=now)
        for name in ('snapshot', 'model', 'testing', 'publishing'):
            hold.advance(name, now=now)
        hold.publish(lambda: URL, now=now)
        self.assertEqual(Queue(self.db).fetch(1)['state'], 'feedback_pending')
        self.assertEqual(Queue(self.db).fetch(1)['feedback_posts'], 0)
        script = test_publish_reconcile.Script()
        recover_open(self._github(script), self._config())
        self.assertEqual(script.posts('/pulls'), [])
        self.assertEqual(script.posts('/git/refs'), [])
        self.assertEqual(len(script.posts('/issues/12/comments')), 1)
        self.assertIn(FEEDBACK_MARKER, script.comments[0])
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        self.assertEqual(Queue(self.db).fetch(1)['state'], 'review')
        report = assert_chain(self, self.db)
        self.assertIn('feedback_retry', {row['event'] for row in report['records']})
        again = test_publish_reconcile.Script()
        again.comments.append(script.comments[0])
        recover_open(self._github(again), self._config())
        self.assertEqual(again.posts('/issues/12/comments'), [])
        self.assertEqual(again.posts('/pulls'), [])
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        assert_chain(self, self.db)

    def test_restart_does_not_continue_the_attempt(self):
        hold = activate(self.db, issue=12, trigger='9')
        hold.advance('snapshot', now=NOW)
        hold.advance('model', now=NOW)
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 1)
        script = test_publish_reconcile.Script()
        with self.assertRaises(Blocked):
            self._drive(script, self.db, self.root / 'restart.breaker', propagate=True)
        self.assertEqual(script.models, 0)
        self.assertEqual(script.posts('/pulls'), [])
        self.assertEqual(script.posts('/git/refs'), [])
        row = Queue(self.db).fetch(1)
        self.assertEqual(row['model_started'], 1)
        self.assertEqual(row['state'], 'interrupted')
        self.assertEqual(row['attempt'], 1)
        report = assert_chain(self, self.db)
        self.assertIn('lease_expire', {item['event'] for item in report['records']})

    def test_token_expiry_blocks_without_a_second_start(self):
        script = test_publish_reconcile.Script()
        self._drive(script, self.db, self.root / 'auth.breaker', mode='ref-401')
        self.assertEqual(script.models, 1)
        self.assertEqual(script.posts('/pulls'), [])
        self.assertEqual(len(script.posts('/git/refs')), 1)
        self.assertEqual(CircuitBreaker(self.root / 'auth.breaker').reason(), 'auth')
        row = Queue(self.db).fetch(1)
        self.assertEqual(row['state'], 'blocked')
        self.assertEqual(row['model_started'], 1)
        report = assert_chain(self, self.db)
        self.assertIn('breaker_latch', {item['event'] for item in report['records']})
        self.assertIn('auth', {item['detail'] for item in report['records']})
        with self.assertRaises(Blocked):
            self._drive(script, self.db, self.root / 'auth.breaker', mode='ref-401', propagate=True)
        self.assertEqual(script.models, 1)
        self.assertEqual(len(script.posts('/git/refs')), 1)
        self.assertEqual(script.posts('/pulls'), [])
        assert_chain(self, self.db)

    def test_network_loss_blocks_without_a_second_post(self):
        script = test_publish_reconcile.Script()
        self._drive(script, self.db, self.root / 'down.breaker', mode='get-down')
        self.assertEqual(script.models, 1)
        self.assertEqual(len(script.posts('/git/refs')), 1)
        self.assertEqual(script.posts('/pulls'), [])
        row = Queue(self.db).fetch(1)
        self.assertEqual(row['state'], 'blocked')
        self.assertEqual(row['result'], 'publish_unreconciled')
        self.assertEqual(row['model_started'], 1)
        self.assertEqual(CircuitBreaker(self.root / 'down.breaker').reason(), 'unreconcilable_write')
        report = assert_chain(self, self.db)
        self.assertIn('publish_unknown', {item['event'] for item in report['records']})
        self.assertIn('breaker_latch', {item['event'] for item in report['records']})
        with self.assertRaises(Blocked):
            self._drive(script, self.db, self.root / 'down.breaker', mode='get-down', propagate=True)
        self.assertEqual(script.models, 1)
        self.assertEqual(len(script.posts('/git/refs')), 1)
        self.assertEqual(script.posts('/pulls'), [])
        assert_chain(self, self.db)

    def test_ledger_corruption_is_not_a_valid_chain(self):
        broken = self.root / 'broken.db'
        broken.write_bytes(self.db.read_bytes()[:80])
        frozen = broken.read_bytes()
        report = Queue(broken, audit=True).verify_export()
        self.assertFalse(report['ok'])
        self.assertEqual(report['kind'], 'truncation')
        self.assertEqual(report['seq'], 0)
        self.assertEqual(report['records'], [])
        with self.assertRaisesRegex(QueueBlocked, 'corrupt'):
            Queue(broken, breaker=CircuitBreaker(self.root / 'broken.breaker'), audit=True).reconcile()
        self.assertEqual(broken.read_bytes(), frozen)
        self.assertEqual(CircuitBreaker(self.root / 'broken.breaker').reason(), 'ledger')
        self.assertEqual(self._pr_count(broken), 0)

    def test_unknown_state_ends_blocked(self):
        conn = sqlite3.connect(self.db)
        conn.execute(
            '''INSERT INTO cf_task_queue_v1 (
                repo, issue, authorization_version, trigger_key, state, attempt, fencing_token,
                owner_hash, lease_until, reserved_at, heartbeat_at, day, model_started, published_url, result
            ) VALUES (?,?,?,?, 'mystery', 1, 4, NULL, ?, ?, NULL, ?, 0, NULL, NULL)''',
            (REPO_KEY, 41, 'auth', 'trig', NOW + LEASE, NOW, DAY))
        conn.commit()
        conn.close()
        queue = Queue(self.db, audit=True)
        self.assertEqual(queue.effective_state(1), 'blocked')
        queue.reconcile(now=NOW)
        row = Queue(self.db).fetch(1)
        self.assertEqual(row['state'], 'blocked')
        self.assertEqual(row['attempt'], 1)
        self.assertEqual(row['model_started'], 0)
        report = assert_chain(self, self.db)
        self.assertIn('unknown_state', {item['detail'] for item in report['records']})
        with self.assertRaisesRegex(QueueBlocked, 'duplicate claim'):
            activate(self.db)
        self.assertEqual(Queue(self.db).fetch(1)['model_started'], 0)
        self.assertEqual(self._pr_count(self.db), 0)

    def test_ledger_proof_preserves_canary_rows_on_a_copy(self):
        source = self.root / 'legacy.db'
        self._legacy(source)
        before = source.read_bytes()
        export_before = self._legacy_values(source)
        report = prove_legacy_rows(source, self.root)
        self.assertTrue(report['ok'])
        self.assertEqual(report['attempt_count_before'], 2)
        self.assertEqual(report['attempt_count_after'], 2)
        self.assertEqual(report['per_issue_before'], ((4, 2),))
        self.assertEqual(report['per_issue_after'], ((4, 2),))
        self.assertTrue(report['row_export_unchanged'])
        self.assertTrue(report['reversible'])
        self.assertTrue(report['source_bytes_unchanged'])
        self.assertTrue(report['whole_file_hash_is_not_the_proof'])
        self.assertTrue(report['copy_file_hash_changed'])
        self.assertNotEqual(report['copy_file_hash_before'], report['copy_file_hash_after_up'])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self._legacy_values(source), export_before)
        copy = self.root / 'ledger-copy.db'
        self.assertEqual(self._legacy_values(copy), export_before)
        text = (self.root / 'legacy-rows.txt').read_text()
        self.assertIn('blocked', text)
        self.assertIn('pr', text)
        self.assertNotIn('whole file hash', text.lower())

    def test_ledger_proof_refuses_state_db_without_fixture(self):
        source = self.root / 'state.db'
        self._legacy(source)
        before = source.read_bytes()
        with self.assertRaisesRegex(LedgerProofError, 'refusing state.db'):
            prove_legacy_rows(source, self.root)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse((self.root / 'ledger-copy.db').exists())
        live = self.root / '.automation'
        live.mkdir()
        live_db = live / 'state.db'
        self._legacy(live_db)
        live_before = live_db.read_bytes()
        with self.assertRaisesRegex(LedgerProofError, 'refusing live ledger'):
            prove_legacy_rows(live_db, self.root, fixture=True)
        self.assertEqual(live_db.read_bytes(), live_before)
        allowed = self.root / 'allowed'
        allowed.mkdir()
        report = prove_legacy_rows(source, allowed, fixture=True)
        self.assertEqual(report['attempt_count_after'], 2)
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue(report['copy_file_hash_changed'])
        self.assertFalse((self.root / 'allowed' / 'state.db').exists())

    def test_launchd_sample_is_not_installed(self):
        plist_path = ROOT / 'docs/automation/com.contractorflow.studio.sample.plist'
        doc = (ROOT / 'docs/automation/P1_LAUNCHD.md').read_text()
        plist = plistlib.loads(plist_path.read_bytes())
        self.assertIs(plist['KeepAlive'], False)
        self.assertIs(plist['RunAtLoad'], False)
        self.assertGreaterEqual(plist['StartInterval'], 120)
        self.assertGreaterEqual(plist['ThrottleInterval'], 120)
        self.assertNotIn('NetworkState', plist)
        self.assertNotIn('UserName', plist)
        command = ' '.join(plist['ProgramArguments'])
        for banned in ('once', 'watch', 'caffeinate', 'pmset', 'sudo', 'launchctl', 'dispatcher'):
            self.assertNotIn(banned, command)
        self.assertNotIn('LaunchAgents', str(plist_path))
        self.assertNotIn('LaunchDaemons', str(plist_path))
        self.assertIn('separate future', doc)
        self.assertIn('not installed', doc.lower())
        self.assertIn('caffeinate', doc)
        self.assertIn('NetworkState', doc)
        sample = (ROOT / 'automation/launchd_sample.py').read_text()
        dispatcher = (ROOT / 'automation/dispatcher.py').read_text()
        self.assertNotIn('subprocess', sample)
        self.assertNotIn('launchctl load', sample)
        self.assertNotIn('launchctl bootstrap', sample)
        self.assertNotIn('launchctl', plist_path.read_text())
        self.assertNotIn('prove_legacy_rows', dispatcher)
        self.assertNotIn('launchctl', dispatcher)
        breaker = self.root / 'queue.db.breaker'
        breaker.write_text('auth\n')
        self.assertEqual(launchd_main(['--breaker', str(breaker)]), 0)
        self.assertEqual(launchd_main(['bootstrap']), 2)
        self.assertEqual(launchd_main(['once']), 2)
        self.assertEqual(launchd_main(['watch']), 2)

    def test_example_settings_omit_p1_keys(self):
        settings = json.loads((ROOT / 'automation/settings.example.json').read_text())
        self.assertIs(settings['enabled'], False)
        self.assertEqual(settings['canary_issue'], 4)
        for key in ('task_queue', 'publish_reconcile', 'audit_chain'):
            self.assertNotIn(key, settings)
        digest = hashlib.sha256((ROOT / '.github/workflows/ci.yml').read_bytes()).hexdigest()
        self.assertEqual(digest, CI_SHA256)
        quiet = self.root / 'quiet.db'
        Queue(quiet).migrate_up()
        script = test_publish_reconcile.Script()
        self._drive(script, quiet, self.root / 'quiet.breaker', audit=False)
        self.assertEqual(script.models, 1)
        self.assertEqual(len(script.posts('/pulls')), 1)
        report = chain_of(quiet)
        self.assertTrue(report['ok'])
        self.assertEqual(report['records'], [])

    def test_chain_recording_requires_explicit_key(self):
        recorded = self.root / 'recorded.db'
        Queue(recorded).migrate_up()
        script = test_publish_reconcile.Script()
        self._drive(script, recorded, self.root / 'recorded.breaker', audit=True)
        self.assertEqual(script.models, 1)
        self.assertEqual(len(script.posts('/pulls')), 1)
        self.assertEqual(len(script.posts('/git/refs')), 1)
        report = assert_chain(self, recorded)
        self.assertIn('claim', {row['event'] for row in report['records']})
        self.assertIn('state', {row['event'] for row in report['records']})
        self.assertGreater(len(report['records']), 1)
        again = test_publish_reconcile.Script()
        with self.assertRaises(Blocked):
            self._drive(again, recorded, self.root / 'recorded.breaker', audit=True, propagate=True)
        self.assertEqual(again.models, 0)
        self.assertEqual(again.posts('/pulls'), [])
        self.assertEqual(Queue(recorded).fetch(1)['model_started'], 1)
        assert_chain(self, recorded)

    def _seed_three(self):
        hold = activate(self.db)
        hold.heartbeat(now=NOW + 1_000)
        hold.advance('snapshot', now=NOW + 1_000)
        self.assertEqual(len(chain_of(self.db)['records']), 3)

    def _copy_db(self, path):
        path.write_bytes(self.db.read_bytes())

    def _tamper(self, path):
        conn = sqlite3.connect(path)
        try:
            conn.execute("UPDATE cf_audit_chain_v1 SET detail='closed' WHERE seq=2")
            conn.commit()
        finally:
            conn.close()

    def _delete_middle(self, path):
        conn = sqlite3.connect(path)
        try:
            conn.execute('DELETE FROM cf_audit_chain_v1 WHERE seq=2')
            conn.commit()
        finally:
            conn.close()

    def _reorder(self, path):
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "UPDATE cf_audit_chain_v1 SET prev_hash=? WHERE seq=2",
                ('ab' * 32,))
            conn.commit()
        finally:
            conn.close()

    def _truncate(self, path):
        conn = sqlite3.connect(path)
        try:
            conn.execute('DELETE FROM cf_audit_chain_v1 WHERE seq=3')
            conn.commit()
        finally:
            conn.close()
        report = chain_of(path)
        self.assertEqual(report['kind'], 'truncation')
        injected = self.root / 'injected.db'
        injected.write_bytes(self.db.read_bytes())
        self._inject_email(injected)
        hidden = chain_of(injected)
        self.assertEqual((hidden['ok'], hidden['kind'], hidden['seq']), (False, 'tamper', 3))
        self.assertNotIn('person@example.com', json.dumps(hidden))

    def _inject_email(self, path):
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                '''SELECT seq, at_ms, event, task_id, state, fencing_token, prev_hash
                   FROM cf_audit_chain_v1 WHERE seq=3''').fetchone()
            seq, at_ms, event, task_id, state, token, prev = row
            detail = 'person@example.com'
            digest = _chain_hash(seq, at_ms, event, task_id, state, token, detail, prev)
            conn.execute(
                'UPDATE cf_audit_chain_v1 SET detail=?, record_hash=? WHERE seq=3',
                (detail, digest))
            conn.execute('UPDATE cf_audit_chain_tip_v1 SET tip_hash=? WHERE id=1', (digest,))
            conn.commit()
        finally:
            conn.close()

    def _legacy(self, path):
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
        conn.execute('CREATE TABLE notices(issue INTEGER, key TEXT, PRIMARY KEY(issue, key))')
        conn.execute("INSERT INTO runs VALUES (7, 4, 'label', 'blocked', 1.5, '2026-11-07', 'synthetic')")
        conn.execute("INSERT INTO runs VALUES (11, 4, 'label-200', 'pr', 2.25, '2026-11-07', NULL)")
        conn.execute("INSERT INTO notices VALUES (4, 'sample-key')")
        conn.commit()
        conn.close()

    def _legacy_values(self, path):
        uri = 'file:' + Path(path).resolve().as_posix() + '?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = list(conn.execute('SELECT id, issue, status, result FROM runs ORDER BY id'))
            notices = list(conn.execute('SELECT issue, key FROM notices ORDER BY issue, key'))
            return rows, notices
        finally:
            conn.close()

    def _pr_count(self, path):
        if not path.is_file() or path.stat().st_size < 100:
            return 0
        try:
            row = Queue(path).fetch(1)
        except QueueBlocked:
            return 0
        return 0 if row['published_url'] is None else 1

    def _config(self, database=None, breaker=None, audit=True):
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
            'publish_reconcile': {'enabled': True, 'breaker': str(breaker or self.root / 'queue.db.breaker')},
        }
        if audit:
            config['audit_chain'] = {'enabled': True}
        return config

    def _github(self, script):
        from automation.dispatcher import GitHub
        api = GitHub('synthetic-token')
        api.api = script.api
        api.pages = script.pages
        api.snapshot = lambda checkout: (SHA, SHA)
        return api

    def _drive(self, script, database, breaker, mode='ok', audit=True, propagate=False):
        script.mode = mode

        def fake_child(args, checkout, timeout, log, env, remote_stop=None, heartbeat=None):
            self.assertNotIn('GITHUB_TOKEN', env)
            if '--json' in args:
                script.models += 1
                (checkout / 'docs').mkdir()
                (checkout / 'docs/sample.md').write_text('SAMPLE MODE\n')
                log.write_text('SIMULATED MODEL; no inference')
            else:
                policy = json.loads((ROOT / 'automation/test_manifest.json').read_text())
                payload = {'success': True, 'count': len(policy['tests']), 'tests': sorted(policy['tests'])}
                log.write_text('SIMULATED TEST WORKER\nCF_TEST_RESULT ' + json.dumps(payload) + '\n')

        def fake_diff(checkout, paths):
            return [('docs/sample.md', (checkout / 'docs/sample.md').read_bytes(), '100644')]

        with tempfile.TemporaryDirectory() as temp, sqlite3.connect(str(Path(temp) / 'runs.db')) as db:
            root = Path(temp)
            (root / 'codex-home').mkdir()
            (root / 'codex-home/auth.json').write_text('SYNTHETIC PRESENCE FIXTURE')
            db.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
            with patch('automation.dispatcher.RUNTIME', root), patch('automation.dispatcher.preflight'), \
                    patch('automation.dispatcher.child', side_effect=fake_child), \
                    patch('automation.dispatcher.prepare'), patch('automation.dispatcher.diff', side_effect=fake_diff):
                try:
                    run_issue(self._github(script), test_automation.issue(), self._config(database, breaker, audit), db)
                except Blocked:
                    if propagate:
                        raise
        return script
