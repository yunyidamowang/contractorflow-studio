"""Single-machine task queue. Not distributed mutual exclusion.

Two processes on one machine are excluded by a local flock plus a SQLite
BEGIN IMMEDIATE transaction. A second machine, a copied database, or a
clock we cannot trust is fail-closed. An expired lease is interrupted for
review; it is not a second model run. publish_unknown is the exception:
an expired publishing row that already recorded a branch becomes
publish_unknown so a later read can identify it. That transition does not
start a model and does not delete the row. Attempt rows are not deleted or
refunded. This module does not migrate a database unless migrate_up or
migrate_down is called, and it refuses a file named state.db.

A breaker object, when attached, is latched on duplicate claim and ledger
corruption. This module never clears that breaker.

audit=True appends a hash chain in the same transaction as each recorded
transition. The chain stays empty unless that flag is set. Opening a database
whose chain does not verify fails closed. verify_export is read-only.
"""
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time


STATES = frozenset({
    'queued', 'claimed', 'snapshot', 'model', 'testing', 'publishing',
    'publish_unknown', 'feedback_pending', 'review', 'blocked', 'stopped',
    'interrupted',
})
TERMINAL = frozenset({'review', 'blocked', 'stopped', 'interrupted'})
_FEEDBACK_CAP = 2
_FEEDBACK_WINDOW_MS = 86_400_000
_BRANCH = re.compile(r'codex/issue-\d+-attempt-[12]-[0-9]+\Z')
_SHA = re.compile(r'[0-9a-f]{40}\Z')
_CHAIN_HASH = re.compile(r'[0-9a-f]{64}\Z')
CHAIN_RECORD_VERSION = 1
GENESIS = hashlib.sha256(b'cf-audit-chain-v1\n').hexdigest()
_CHAIN_EVENTS = frozenset({
    'claim', 'lease_renew', 'lease_expire', 'fencing_reject', 'state',
    'publish_unknown', 'reconcile_result', 'feedback_retry', 'breaker_latch',
})
_BREAKER_REASONS = frozenset({
    'auth', 'branch_protection', 'policy', 'ledger',
    'duplicate_claim', 'unreconcilable_write', 'safety_test',
})
_DETAILS = frozenset({
    'attempt_reserved', 'lease_renewed', 'lease_expired', 'clock_moved_backwards',
    'closed', 'unknown_state', 'publish_recorded', 'target_recorded',
    'feedback_post', 'publish_unknown', 'publish_exists', 'publish_unreconciled',
    'publish_absent', 'publish_partial', 'feedback_recorded', 'feedback_capped',
    'feedback_unknown', 'duplicate_rejected', 'fencing_rejected', 'redacted',
    'queued', 'claimed', 'snapshot', 'model', 'testing', 'publishing',
    'feedback_pending', 'review', 'blocked', 'stopped', 'interrupted',
    'auth', 'branch_protection', 'policy', 'ledger', 'duplicate_claim',
    'unreconcilable_write', 'safety_test',
})
_DETAIL_ALIAS = {
    'heartbeat': 'lease_renewed',
    'recorded': 'publish_recorded',
    'lease expired': 'lease_expired',
    'clock moved backwards': 'clock_moved_backwards',
}
# feedback_pending stays put on a normal failure so a later slice can retry
# the comment without starting the model again. Lease expiry still interrupts it.
HOLDABLE = frozenset({
    'claimed', 'snapshot', 'model', 'testing', 'publishing', 'feedback_pending',
})
FORWARD = {
    'claimed': frozenset({'snapshot', 'blocked', 'stopped'}),
    'snapshot': frozenset({'model', 'blocked', 'stopped'}),
    'model': frozenset({'testing', 'blocked', 'stopped'}),
    'testing': frozenset({'publishing', 'blocked', 'stopped'}),
    'publishing': frozenset({'feedback_pending', 'blocked', 'stopped'}),
    'feedback_pending': frozenset({'review'}),
}
VISIBLE = (
    'id', 'repo', 'issue', 'authorization_version', 'trigger_key', 'state',
    'attempt', 'fencing_token', 'lease_until', 'reserved_at', 'heartbeat_at',
    'day', 'model_started', 'published_url', 'result',
    'publish_branch', 'publish_commit', 'feedback_posts',
)
_HEADER = b'SQLite format 3\x00'
_UP = (
    '''CREATE TABLE cf_schema_migration (
        version INTEGER NOT NULL PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL
    )''',
    '''CREATE TABLE cf_task_queue_v1 (
        id INTEGER PRIMARY KEY,
        repo TEXT NOT NULL,
        issue INTEGER NOT NULL,
        authorization_version TEXT NOT NULL,
        trigger_key TEXT NOT NULL,
        state TEXT NOT NULL,
        attempt INTEGER NOT NULL,
        fencing_token INTEGER NOT NULL,
        owner_hash TEXT,
        lease_until INTEGER,
        reserved_at INTEGER NOT NULL,
        heartbeat_at INTEGER,
        day TEXT NOT NULL,
        model_started INTEGER NOT NULL,
        published_url TEXT,
        result TEXT,
        publish_branch TEXT,
        publish_commit TEXT,
        feedback_posts INTEGER NOT NULL DEFAULT 0,
        feedback_at INTEGER,
        UNIQUE (repo, issue, authorization_version, trigger_key)
    )''',
    '''CREATE TABLE cf_queue_audit_v1 (
        id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL,
        event TEXT NOT NULL,
        state TEXT NOT NULL,
        fencing_token INTEGER NOT NULL,
        at_ms INTEGER NOT NULL,
        detail TEXT NOT NULL
    )''',
    '''CREATE TABLE cf_audit_chain_v1 (
        seq INTEGER PRIMARY KEY,
        record_version INTEGER NOT NULL,
        at_ms INTEGER NOT NULL,
        event TEXT NOT NULL,
        task_id INTEGER NOT NULL,
        state TEXT NOT NULL,
        fencing_token INTEGER NOT NULL,
        detail TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        record_hash TEXT NOT NULL
    )''',
    '''CREATE TABLE cf_audit_chain_tip_v1 (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        length INTEGER NOT NULL,
        tip_hash TEXT NOT NULL
    )''',
)


class QueueError(Exception):
    pass


class QueueBlocked(QueueError):
    pass


class QueueFenced(QueueError):
    pass


class _CommitAndRaise(Exception):
    def __init__(self, error):
        self.error = error


def _bound_text(value, limit):
    if type(value) is not str or not value or len(value) > limit or '\x00' in value or '\n' in value:
        raise QueueBlocked('invalid queue key')
    return value


def _bound_count(value, upper):
    if type(value) is not int or not 0 <= value <= upper:
        raise QueueBlocked('attempt budget exhausted')
    return value


class Hold:
    """In-memory capability for the process that claimed the row.

    The database stores only a hash of the owner token. A restarted process
    cannot rebuild that token, and this object is not reloaded from disk.
    """

    def __init__(self, queue, task_id, owner, token, attempt):
        self.queue = queue
        self.task_id = task_id
        self.owner = owner
        self.token = token
        self.attempt = attempt
        self.heartbeat_seconds = queue.heartbeat_ms // 1000

    def advance(self, state, now=None):
        if state not in STATES or state in ('queued', 'claimed', 'interrupted'):
            raise QueueBlocked('illegal transition')
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            row = self._require_live(conn, now, HOLDABLE)
            if state not in FORWARD.get(row['state'], frozenset()):
                raise QueueBlocked('illegal transition')
            started = row['model_started']
            if state == 'model':
                if started:
                    raise QueueBlocked('model already started')
                started = 1
            self.queue._write_holder(conn, row, state, self.token, now, started, 'advance', state)
        return self

    def heartbeat(self, now=None):
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            row = self._require_live(conn, now, HOLDABLE)
            self.queue._write_holder(conn, row, row['state'], self.token, now, row['model_started'], 'heartbeat', 'heartbeat')
        return self

    def assert_live(self, now=None):
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            self._require_live(conn, now, HOLDABLE)
        return self

    def publish(self, callback, now=None):
        """Run callback only after the fencing token and lease both match.

        The callback must not touch this queue. It is not invoked when the
        token is stale or the lease has expired.
        """
        if not callable(callback):
            raise QueueBlocked('publish callback missing')
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            row = self._require_live(conn, now, frozenset({'publishing'}))
            value = callback()
            if type(value) is not str or not value or len(value) > 500 or '\n' in value or '\x00' in value:
                raise QueueBlocked('publish result rejected')
            self.queue._write_holder(conn, row, 'feedback_pending', self.token, now, row['model_started'], 'publish_accepted', 'recorded')
            conn.execute('UPDATE cf_task_queue_v1 SET published_url=? WHERE id=? AND fencing_token=?', (value, row['id'], self.token))
            return value

    def note_publish_target(self, branch, commit, now=None):
        """Record the branch and commit before the branch POST. Token stays put."""
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            row = self._require_live(conn, now, frozenset({'publishing'}))
            if not _known_branch(branch) or not branch.startswith(f"codex/issue-{row['issue']}-attempt-{row['attempt']}-"):
                raise QueueBlocked('invalid publish target')
            if type(commit) is not str or not _SHA.fullmatch(commit):
                raise QueueBlocked('invalid publish target')
            conn.execute(
                '''UPDATE cf_task_queue_v1 SET publish_branch=?, publish_commit=?
                   WHERE id=? AND fencing_token=? AND state='publishing' ''',
                (branch, commit, row['id'], self.token))
            current = conn.execute(
                'SELECT publish_branch, publish_commit, fencing_token, state FROM cf_task_queue_v1 WHERE id=?',
                (row['id'],)).fetchone()
            if (current is None or current['publish_branch'] != branch or current['publish_commit'] != commit
                    or current['fencing_token'] != self.token or current['state'] != 'publishing'):
                raise QueueFenced('fencing token rejected')
            self.queue._audit(conn, row['id'], 'publish_target', 'publishing', self.token, now, 'target_recorded')
        return self

    def mark_publish_unknown(self, now=None):
        """Stop writes for this holder. The branch already stored is kept."""
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            row = self._require_live(conn, now, frozenset({'publishing'}))
            self.queue._enter_unknown(conn, row, now)
        return self

    def close_as(self, state, now=None):
        if state not in ('blocked', 'stopped'):
            raise QueueBlocked('close state rejected')
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            row = self._row(conn)
            # feedback_pending means the publish was recorded. Do not turn that into a rerunnable failure.
            # A recorded branch is publish_unknown, not a silent blocked row that could be retried.
            if row['state'] not in {'claimed', 'snapshot', 'model', 'testing', 'publishing'} or not self._matches(row):
                return self
            if type(row['reserved_at']) is not int or now < row['reserved_at']:
                self.queue._terminal(conn, row, 'blocked', now, 'clock moved backwards')
                return self
            if row['state'] == 'publishing' and _known_branch(row['publish_branch']):
                self.queue._enter_unknown(conn, row, now)
                return self
            self.queue._terminal(conn, row, state, now, 'closed')
        return self

    def _reject_fence(self, conn, row, now):
        if self.queue.audit:
            token = row['fencing_token'] if type(row['fencing_token']) is int and row['fencing_token'] >= 0 else 0
            state = row['state'] if row['state'] in STATES else 'blocked'
            self.queue._append_chain(conn, row['id'], 'fencing_reject', state, token, 'fencing_rejected', now)
            raise _CommitAndRaise(QueueFenced('fencing token rejected'))
        raise QueueFenced('fencing token rejected')

    def _row(self, conn):
        row = conn.execute('SELECT * FROM cf_task_queue_v1 WHERE id=?', (self.task_id,)).fetchone()
        if row is None:
            raise QueueBlocked('missing task')
        return row

    def _matches(self, row):
        if type(row['fencing_token']) is not int or row['fencing_token'] != self.token:
            return False
        if type(row['owner_hash']) is not str:
            return False
        digest = hashlib.sha256(self.owner.encode()).hexdigest()
        return hmac.compare_digest(digest, row['owner_hash'])

    def _require_live(self, conn, now, allowed):
        row = self._row(conn)
        if row['state'] not in STATES:
            self.queue._terminal(conn, row, 'blocked', now, 'unknown_state', event='unknown_state')
            raise _CommitAndRaise(QueueBlocked('unknown state'))
        if not self._matches(row):
            self._reject_fence(conn, row, now)
        if type(row['reserved_at']) is not int or now < row['reserved_at']:
            self.queue._terminal(conn, row, 'blocked', now, 'clock moved backwards')
            raise _CommitAndRaise(QueueBlocked('clock moved backwards'))
        if type(row['lease_until']) is not int or now >= row['lease_until']:
            self.queue._terminal(conn, row, 'interrupted', now, 'lease expired', event='interrupted')
            raise _CommitAndRaise(QueueFenced('lease expired'))
        if row['state'] not in allowed:
            self._reject_fence(conn, row, now)
        return row


class Queue:
    def __init__(self, database, *, lock_path=None, lease_ms=120_000, heartbeat_ms=30_000, clock=None, breaker=None, audit=False):
        self.database = Path(database)
        self.breaker = breaker
        self.audit = audit is True
        if self.database.name == 'state.db' or self.database.is_symlink():
            raise QueueBlocked('queue database must not be the legacy ledger')
        if (type(lease_ms) is not int or type(heartbeat_ms) is not int
                or not 1000 <= heartbeat_ms < lease_ms <= 1_200_000):
            raise QueueBlocked('invalid lease')
        self.lease_ms = lease_ms
        self.heartbeat_ms = heartbeat_ms
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.lock_path = Path(lock_path) if lock_path else Path(str(self.database) + '.lock')
        if self.lock_path.name == 'state.db' or self.lock_path.is_symlink():
            raise QueueBlocked('queue database must not be the legacy ledger')

    def migrate_up(self):
        """Create v1 tables. Does not alter, delete, or renumber other tables."""
        fd = self._acquire_lock()
        conn = None
        try:
            conn = sqlite3.connect(self.database, isolation_level=None, timeout=5)
            try:
                conn.execute('BEGIN IMMEDIATE')
                version = _version(conn)
                if version == 1:
                    raise QueueBlocked('schema already applied')
                if version != 0:
                    raise QueueBlocked('schema mismatch')
                for statement in _UP:
                    conn.execute(statement)
                conn.execute(
                    'INSERT INTO cf_audit_chain_tip_v1(id, length, tip_hash) VALUES (1, 0, ?)',
                    (GENESIS,))
                conn.execute(
                    'INSERT INTO cf_schema_migration(version, name, applied_at) VALUES (1, ?, ?)',
                    ('cf_task_queue_v1', 'explicit'))
                conn.commit()
            except QueueBlocked:
                conn.rollback()
                raise
            except sqlite3.Error:
                conn.rollback()
                self._latch('ledger')
                raise QueueBlocked('queue database corrupt') from None
        finally:
            if conn is not None:
                conn.close()
            self._release_lock(fd)

    def migrate_down(self):
        """Drop only the v1 queue tables. Legacy tables are not named here."""
        fd = self._acquire_lock()
        conn = None
        try:
            if not self.database.is_file():
                raise QueueBlocked('queue database missing')
            conn = sqlite3.connect(self.database, isolation_level=None, timeout=5)
            try:
                conn.execute('BEGIN IMMEDIATE')
                if _version(conn) != 1:
                    raise QueueBlocked('schema mismatch')
                conn.execute('DROP TABLE cf_audit_chain_v1')
                conn.execute('DROP TABLE cf_audit_chain_tip_v1')
                conn.execute('DROP TABLE cf_queue_audit_v1')
                conn.execute('DROP TABLE cf_task_queue_v1')
                conn.execute('DROP TABLE cf_schema_migration')
                conn.commit()
            except QueueBlocked:
                conn.rollback()
                raise
            except sqlite3.Error:
                conn.rollback()
                self._latch('ledger')
                raise QueueBlocked('queue database corrupt') from None
        finally:
            if conn is not None:
                conn.close()
            self._release_lock(fd)

    def enqueue(self, *, repo, issue, authorization_version, trigger, day, max_attempts, max_daily,
                prior_attempts=0, prior_daily=0, now=None):
        """Persist a queued attempt. Does not claim it and does not start a model."""
        self._breaker_check()
        key = self._key(repo, issue, authorization_version, trigger, day, max_attempts, max_daily, prior_attempts, prior_daily)
        now = self._now(now)
        with self._exclusive() as conn:
            self._breaker_check()
            existing = _by_key(conn, key)
            if existing is not None:
                self._duplicate(conn, existing['id'], existing['state'], existing['fencing_token'], now)
            attempt = _next_attempt(conn, key)
            conn.execute(
                '''INSERT INTO cf_task_queue_v1 (
                    repo, issue, authorization_version, trigger_key, state, attempt, fencing_token,
                    owner_hash, lease_until, reserved_at, heartbeat_at, day, model_started, published_url, result
                ) VALUES (?,?,?,?, 'queued', ?, 0, NULL, ?, ?, NULL, ?, 0, NULL, NULL)''',
                (key['repo'], key['issue'], key['authorization_version'], key['trigger'], attempt,
                 now + self.lease_ms, now, key['day']))
            task_id = conn.execute('SELECT id FROM cf_task_queue_v1 WHERE repo=? AND issue=? AND authorization_version=? AND trigger_key=?',
                (key['repo'], key['issue'], key['authorization_version'], key['trigger'])).fetchone()[0]
            self._audit(conn, task_id, 'reserve', 'queued', 0, now, 'attempt_reserved')
            return task_id

    def claim(self, *, repo, issue, authorization_version, trigger, now=None):
        self._breaker_check()
        key = self._identity(repo, issue, authorization_version, trigger)
        now = self._now(now)
        with self._exclusive() as conn:
            self._breaker_check()
            row = _by_key(conn, key)
            if row is None or row['state'] != 'queued' or row['owner_hash'] is not None:
                self._duplicate(conn, 0 if row is None else row['id'],
                                'blocked' if row is None else row['state'],
                                0 if row is None else row['fencing_token'], now)
            if type(row['reserved_at']) is not int or now < row['reserved_at']:
                self._terminal(conn, row, 'blocked', now, 'clock moved backwards')
                raise _CommitAndRaise(QueueBlocked('clock moved backwards'))
            if type(row['lease_until']) is not int or now >= row['lease_until']:
                self._terminal(conn, row, 'interrupted', now, 'lease expired', event='interrupted')
                raise _CommitAndRaise(QueueBlocked('lease expired'))
            return self._grant(conn, row, now, 'claim', 'claimed')

    def activate(self, *, repo, issue, authorization_version, trigger, day, max_attempts, max_daily,
                 prior_attempts=0, prior_daily=0, now=None):
        """Insert one claimed attempt and commit it before returning.

        An existing key is refused. This does not adopt a row left by a dead
        process, so a restart cannot continue that attempt.
        """
        self._breaker_check()
        key = self._key(repo, issue, authorization_version, trigger, day, max_attempts, max_daily, prior_attempts, prior_daily)
        now = self._now(now)
        with self._exclusive() as conn:
            self._breaker_check()
            existing = _by_key(conn, key)
            if existing is not None:
                self._duplicate(conn, existing['id'], existing['state'], existing['fencing_token'], now)
            attempt = _next_attempt(conn, key)
            owner = secrets.token_hex(16)
            token = 1
            cur = conn.execute(
                '''INSERT INTO cf_task_queue_v1 (
                    repo, issue, authorization_version, trigger_key, state, attempt, fencing_token,
                    owner_hash, lease_until, reserved_at, heartbeat_at, day, model_started, published_url, result
                ) VALUES (?,?,?,?, 'claimed', ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL)''',
                (key['repo'], key['issue'], key['authorization_version'], key['trigger'], attempt, token,
                 _hash(owner), now + self.lease_ms, now, now, key['day']))
            task_id = cur.lastrowid
            self._audit(conn, task_id, 'reserve', 'claimed', token, now, 'attempt_reserved')
            return Hold(self, task_id, owner, token, attempt)

    def reconcile(self, now=None):
        """Expire leases and quarantine unknown states. Never claims or starts a model."""
        now = self._now(now)
        with self._exclusive() as conn:
            rows = list(conn.execute('SELECT * FROM cf_task_queue_v1 ORDER BY id'))
            for row in rows:
                if row['state'] not in STATES:
                    self._terminal(conn, row, 'blocked', now, 'unknown_state', event='unknown_state')
                    continue
                if row['state'] in TERMINAL or row['state'] == 'publish_unknown':
                    continue
                if type(row['reserved_at']) is not int or now < row['reserved_at']:
                    self._terminal(conn, row, 'blocked', now, 'clock moved backwards')
                    raise _CommitAndRaise(QueueBlocked('clock moved backwards'))
                if (row['state'] == 'publishing' and _known_branch(row['publish_branch'])
                        and (type(row['lease_until']) is not int or now >= row['lease_until'])):
                    self._enter_unknown(conn, row, now)
                    continue
                if type(row['lease_until']) is not int or now >= row['lease_until']:
                    self._terminal(conn, row, 'interrupted', now, 'lease expired', event='interrupted')

    def fetch(self, task_id):
        if type(task_id) is not int or task_id < 1:
            raise QueueBlocked('missing task')
        with self._exclusive() as conn:
            columns = ', '.join(VISIBLE)
            row = conn.execute(f'SELECT {columns} FROM cf_task_queue_v1 WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise QueueBlocked('missing task')
            return {key: row[key] for key in VISIBLE}

    def effective_state(self, task_id):
        state = self.fetch(task_id)['state']
        return state if state in STATES else 'blocked'

    def verify_export(self):
        """Read-only chain report. Does not repair a bad chain or write the database."""
        if self.database.name == 'state.db' or self.database.is_symlink():
            raise QueueBlocked('queue database must not be the legacy ledger')
        return read_chain_report(self.database)

    def note_breaker(self, reason, now=None):
        """Append one redacted breaker event. Does nothing unless this queue records the chain."""
        if not self.audit:
            return None
        if reason not in _BREAKER_REASONS:
            reason = 'unreconcilable_write'
        now = self._now(now)
        with self._exclusive() as conn:
            self._append_chain(conn, 0, 'breaker_latch', 'blocked', 0, reason, now)
        return reason

    def audit_export(self):
        with self._exclusive() as conn:
            rows = conn.execute(
                'SELECT id, task_id, event, state, fencing_token, at_ms, detail '
                'FROM cf_queue_audit_v1 ORDER BY id').fetchall()
            return [
                (row['id'], row['task_id'], row['event'], row['state'], row['fencing_token'], row['at_ms'], row['detail'])
                for row in rows]

    def snapshot_rows(self):
        with self._exclusive() as conn:
            columns = ', '.join(VISIBLE)
            rows = conn.execute(f'SELECT {columns} FROM cf_task_queue_v1 ORDER BY id').fetchall()
            return [{key: row[key] for key in VISIBLE} for row in rows]

    def apply_reconciliation(self, task_id, outcome, url=None, now=None):
        """Record a read-only decision. Does not start a model or create a remote object."""
        if outcome not in ('exists', 'absent', 'partial', 'unknown'):
            raise QueueBlocked('invalid reconciliation')
        now = self._now(now)
        with self._exclusive() as conn:
            row = self._task(conn, task_id)
            if row['state'] != 'publish_unknown':
                raise QueueBlocked('illegal transition')
            if outcome == 'exists':
                if not _safe_url(url):
                    self._latch('unreconcilable_write', conn, row['id'], row['state'], row['fencing_token'], now)
                    self._move_frozen(conn, row, 'blocked', now, 'publish_unreconciled')
                    return
                self._move_frozen(conn, row, 'feedback_pending', now, 'publish_exists', url=url)
                return
            if outcome == 'unknown':
                self._latch('unreconcilable_write', conn, row['id'], row['state'], row['fencing_token'], now)
                self._move_frozen(conn, row, 'blocked', now, 'publish_unreconciled')
                return
            detail = 'publish_absent' if outcome == 'absent' else 'publish_partial'
            self._move_frozen(conn, row, 'blocked', now, detail)

    def begin_feedback_post(self, task_id, now=None):
        """Count one feedback POST before it is sent. The count is not cleared."""
        self._breaker_check()
        now = self._now(now)
        with self._exclusive() as conn:
            self._breaker_check()
            row = self._task(conn, task_id)
            if row['state'] != 'feedback_pending' or row['model_started'] != 1 or not row['published_url']:
                raise QueueBlocked('illegal transition')
            posts = row['feedback_posts']
            if type(posts) is not int or not 0 <= posts <= _FEEDBACK_CAP:
                self._latch('ledger', conn, row['id'], row['state'], row['fencing_token'], now)
                raise _CommitAndRaise(QueueBlocked('queue database corrupt'))
            if posts >= _FEEDBACK_CAP:
                raise QueueBlocked('feedback cap reached')
            started = row['feedback_at']
            if started is not None:
                if type(started) is not int or now < started:
                    self._terminal(conn, row, 'blocked', now, 'clock moved backwards')
                    raise _CommitAndRaise(QueueBlocked('clock moved backwards'))
                if now - started > _FEEDBACK_WINDOW_MS:
                    raise QueueBlocked('feedback cap reached')
            at = started if type(started) is int else now
            cur = conn.execute(
                '''UPDATE cf_task_queue_v1 SET feedback_posts=?, feedback_at=?
                   WHERE id=? AND state='feedback_pending' AND feedback_posts=?''',
                (posts + 1, at, row['id'], posts))
            if cur.rowcount != 1:
                raise QueueFenced('fencing token rejected')
            self._audit(conn, row['id'], 'feedback_attempt', 'feedback_pending', row['fencing_token'], now, 'feedback_post')
            return posts + 1

    def complete_feedback(self, task_id, now=None):
        self._breaker_check()
        now = self._now(now)
        with self._exclusive() as conn:
            self._breaker_check()
            row = self._task(conn, task_id)
            if row['state'] != 'feedback_pending' or row['model_started'] != 1:
                raise QueueBlocked('illegal transition')
            self._move_frozen(conn, row, 'review', now, 'feedback_recorded')

    def block_feedback(self, task_id, detail, now=None):
        if detail not in ('feedback_capped', 'feedback_unknown'):
            raise QueueBlocked('close state rejected')
        now = self._now(now)
        with self._exclusive() as conn:
            row = self._task(conn, task_id)
            if row['state'] != 'feedback_pending':
                raise QueueBlocked('illegal transition')
            self._move_frozen(conn, row, 'blocked', now, detail)

    def _grant(self, conn, row, now, event, detail):
        owner = secrets.token_hex(16)
        token = row['fencing_token'] + 1
        if type(row['fencing_token']) is not int or token <= row['fencing_token']:
            raise QueueBlocked('fencing token rejected')
        conn.execute(
            '''UPDATE cf_task_queue_v1
               SET state='claimed', fencing_token=?, owner_hash=?, lease_until=?, heartbeat_at=?
               WHERE id=?''',
            (token, _hash(owner), now + self.lease_ms, now, row['id']))
        self._audit(conn, row['id'], event, 'claimed', token, now, detail)
        return Hold(self, row['id'], owner, token, row['attempt'])

    def _write_holder(self, conn, row, state, token, now, started, event, detail):
        conn.execute(
            '''UPDATE cf_task_queue_v1
               SET state=?, fencing_token=?, model_started=?, lease_until=?, heartbeat_at=?
               WHERE id=? AND fencing_token=?''',
            (state, token, started, now + self.lease_ms, now, row['id'], token))
        current = conn.execute(
            'SELECT state, fencing_token, model_started FROM cf_task_queue_v1 WHERE id=?',
            (row['id'],)).fetchone()
        if current is None or current['state'] != state or current['fencing_token'] != token or current['model_started'] != started:
            raise QueueFenced('fencing token rejected')
        self._audit(conn, row['id'], event, state, token, now, detail)

    def _terminal(self, conn, row, state, now, detail, event=None):
        if state not in TERMINAL:
            raise QueueBlocked('close state rejected')
        previous = row['fencing_token'] if type(row['fencing_token']) is int and row['fencing_token'] >= 0 else 0
        token = previous + 1
        conn.execute(
            '''UPDATE cf_task_queue_v1
               SET state=?, fencing_token=?, owner_hash=NULL, result=?
               WHERE id=? AND fencing_token IS ?''',
            (state, token, detail, row['id'], row['fencing_token']))
        current = conn.execute(
            'SELECT state, fencing_token, model_started, attempt FROM cf_task_queue_v1 WHERE id=?',
            (row['id'],)).fetchone()
        if (current is None or current['state'] != state or current['fencing_token'] != token
                or current['model_started'] != row['model_started'] or current['attempt'] != row['attempt']):
            raise QueueBlocked('missing task')
        self._audit(conn, row['id'], event or 'terminal', state, token, now, detail)

    def _audit(self, conn, task_id, event, state, token, now, detail):
        conn.execute(
            '''INSERT INTO cf_queue_audit_v1 (task_id, event, state, fencing_token, at_ms, detail)
               VALUES (?,?,?,?,?,?)''',
            (task_id, event, state, token, now, detail))
        if self.audit:
            self._append_chain(conn, task_id, _chain_event_name(event, state, detail), state, token, detail, now)

    def _append_chain(self, conn, task_id, event, state, token, detail, now):
        if not self.audit:
            return
        event = event if event in _CHAIN_EVENTS else 'state'
        state = state if state in STATES else 'blocked'
        detail = _chain_detail(detail)
        if type(task_id) is not int or task_id < 0:
            task_id = 0
        if type(token) is not int or token < 0:
            token = 0
        if type(now) is not int or now < 0 or now > 10**15:
            raise QueueBlocked('audit chain failed')
        tip = conn.execute('SELECT length, tip_hash FROM cf_audit_chain_tip_v1 WHERE id=1').fetchone()
        if tip is None or type(tip['length']) is not int or tip['length'] < 0 or not _CHAIN_HASH.fullmatch(tip['tip_hash'] or ''):
            raise QueueBlocked('audit chain failed')
        seq = tip['length'] + 1
        prev = tip['tip_hash']
        digest = _chain_hash(seq, now, event, task_id, state, token, detail, prev)
        conn.execute(
            '''INSERT INTO cf_audit_chain_v1 (
                seq, record_version, at_ms, event, task_id, state, fencing_token, detail, prev_hash, record_hash
            ) VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (seq, CHAIN_RECORD_VERSION, now, event, task_id, state, token, detail, prev, digest))
        current = conn.execute(
            'UPDATE cf_audit_chain_tip_v1 SET length=?, tip_hash=? WHERE id=1 AND length=? AND tip_hash=?',
            (seq, digest, tip['length'], prev))
        if current.rowcount != 1:
            raise QueueBlocked('audit chain failed')

    def _now(self, now):
        if now is None:
            now = self.clock()
        if type(now) is not int or now < 0 or now > 10**15:
            raise QueueBlocked('clock invalid')
        return now

    def _identity(self, repo, issue, authorization_version, trigger):
        if type(issue) is not int or not 1 <= issue <= 1_000_000_000:
            raise QueueBlocked('invalid queue key')
        return {
            'repo': _bound_text(repo, 200),
            'issue': issue,
            'authorization_version': _bound_text(authorization_version, 200),
            'trigger': _bound_text(trigger, 200),
        }

    def _key(self, repo, issue, authorization_version, trigger, day, max_attempts, max_daily, prior_attempts, prior_daily):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise QueueBlocked('attempt budget exhausted')
        if type(max_daily) is not int or not 1 <= max_daily <= 3:
            raise QueueBlocked('attempt budget exhausted')
        if len(day) != 10 or day[4] != '-' or day[7] != '-' or not day.replace('-', '').isdigit():
            raise QueueBlocked('invalid queue key')
        identity = self._identity(repo, issue, authorization_version, trigger)
        identity.update({
            'day': day,
            'max_attempts': max_attempts,
            'max_daily': max_daily,
            'prior_attempts': _bound_count(prior_attempts, 1_000_000),
            'prior_daily': _bound_count(prior_daily, 1_000_000),
        })
        return identity

    def _exclusive(self):
        return _Exclusive(self)

    def _latch(self, reason, conn=None, task_id=0, state='blocked', token=0, now=0):
        if reason not in _BREAKER_REASONS:
            reason = 'unreconcilable_write'
        already = False
        if self.breaker is not None:
            try:
                already = self.breaker.latched()
            except Exception:
                already = True
        if self.audit and conn is not None and self.breaker is not None and not already:
            safe_state = state if state in STATES else 'blocked'
            safe_token = token if type(token) is int and token >= 0 else 0
            safe_id = task_id if type(task_id) is int and task_id >= 0 else 0
            self._append_chain(conn, safe_id, 'breaker_latch', safe_state, safe_token, reason, now if type(now) is int else 0)
        breaker = self.breaker
        if breaker is None:
            return
        try:
            breaker.latch(reason)
        except Exception:
            return

    def _breaker_check(self):
        if self.breaker is None:
            return
        try:
            self.breaker.assert_closed()
        except Exception:
            raise QueueBlocked('circuit breaker latched') from None

    def _duplicate(self, conn, task_id, state, token, now):
        if self.audit:
            safe_state = state if state in STATES else 'blocked'
            safe_token = token if type(token) is int and token >= 0 else 0
            safe_id = task_id if type(task_id) is int and task_id >= 0 else 0
            self._append_chain(conn, safe_id, 'claim', safe_state, safe_token, 'duplicate_rejected', now)
        self._latch('duplicate_claim', conn, task_id, state, token, now)
        raise _CommitAndRaise(QueueBlocked('duplicate claim'))

    def _task(self, conn, task_id):
        if type(task_id) is not int or task_id < 1:
            raise QueueBlocked('missing task')
        row = conn.execute('SELECT * FROM cf_task_queue_v1 WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise QueueBlocked('missing task')
        return row

    def _enter_unknown(self, conn, row, now):
        if row['state'] != 'publishing':
            raise QueueBlocked('illegal transition')
        self._move_frozen(conn, row, 'publish_unknown', now, 'publish_unknown')

    def _move_frozen(self, conn, row, state, now, detail, url=None):
        if state not in ('publish_unknown', 'feedback_pending', 'blocked', 'review'):
            raise QueueBlocked('illegal transition')
        previous = row['fencing_token']
        if type(previous) is not int or previous < 0:
            raise QueueBlocked('fencing token rejected')
        token = previous + 1
        if url is None:
            conn.execute(
                '''UPDATE cf_task_queue_v1
                   SET state=?, fencing_token=?, owner_hash=NULL, result=?
                   WHERE id=? AND fencing_token=?''',
                (state, token, detail, row['id'], previous))
        else:
            conn.execute(
                '''UPDATE cf_task_queue_v1
                   SET state=?, fencing_token=?, owner_hash=NULL, result=?, published_url=?
                   WHERE id=? AND fencing_token=?''',
                (state, token, detail, url, row['id'], previous))
        current = conn.execute(
            'SELECT state, fencing_token, model_started, attempt, published_url FROM cf_task_queue_v1 WHERE id=?',
            (row['id'],)).fetchone()
        if (current is None or current['state'] != state or current['fencing_token'] != token
                or current['model_started'] != row['model_started'] or current['attempt'] != row['attempt']):
            raise QueueBlocked('missing task')
        if url is not None and current['published_url'] != url:
            raise QueueBlocked('publish result rejected')
        self._audit(conn, row['id'], 'reconcile', state, token, now, detail)

    def _assert_header(self):
        if self.database.name == 'state.db' or self.database.is_symlink():
            raise QueueBlocked('queue database must not be the legacy ledger')
        if not self.database.is_file():
            raise QueueBlocked('queue database missing')
        try:
            with self.database.open('rb') as handle:
                header = handle.read(16)
        except OSError:
            self._latch('ledger')
            raise QueueBlocked('queue database unreadable') from None
        if header != _HEADER:
            self._latch('ledger')
            raise QueueBlocked('queue database corrupt')

    def _read_only_check(self):
        self._assert_header()
        uri = 'file:' + _uri(self.database) + '?mode=ro'
        try:
            ro = sqlite3.connect(uri, uri=True, isolation_level=None)
        except sqlite3.Error:
            self._latch('ledger')
            raise QueueBlocked('queue database corrupt') from None
        try:
            try:
                check = ro.execute('PRAGMA integrity_check').fetchone()
                version = _version(ro)
                report = verify_chain(ro) if version == 1 else None
            except QueueBlocked:
                self._latch('ledger')
                raise
            except sqlite3.Error:
                self._latch('ledger')
                raise QueueBlocked('queue database corrupt') from None
        finally:
            ro.close()
        if check is None or check[0] != 'ok':
            self._latch('ledger')
            raise QueueBlocked('queue database corrupt')
        if version != 1:
            self._latch('ledger')
            raise QueueBlocked('schema mismatch')
        if report is None or not report['ok']:
            self._latch('ledger')
            raise QueueBlocked('audit chain failed')

    def _open_checked(self):
        self._read_only_check()
        try:
            conn = sqlite3.connect(self.database, isolation_level=None, timeout=5)
        except sqlite3.Error:
            self._latch('ledger')
            raise QueueBlocked('queue database corrupt') from None
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute('PRAGMA foreign_keys=ON')
        except sqlite3.Error:
            conn.close()
            raise QueueBlocked('queue database corrupt') from None
        return conn

    def _acquire_lock(self):
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.lock_path, flags, 0o600)
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            raise QueueBlocked('queue lock unavailable') from None
        return fd

    def _release_lock(self, fd):
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


class _Exclusive:
    def __init__(self, queue):
        self.queue = queue

    def __enter__(self):
        self.fd = None
        self.conn = None
        self.pending = None
        try:
            self.queue._assert_header()
            self.fd = self.queue._acquire_lock()
            self.conn = self.queue._open_checked()
            self.conn.execute('BEGIN IMMEDIATE')
            return self.conn
        except Exception:
            self._rollback()
            self._close()
            raise

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            elif exc_type is _CommitAndRaise:
                self.conn.commit()
                self.pending = exc.error
            else:
                self._rollback()
        except Exception:
            self._rollback()
            self._close()
            raise
        self._close()
        if self.pending is not None:
            raise self.pending from None
        return False

    def _rollback(self):
        if self.conn is not None:
            try:
                self.conn.rollback()
            except sqlite3.Error:
                pass

    def _close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        if self.fd is not None:
            self.queue._release_lock(self.fd)
            self.fd = None


def _known_branch(value):
    return type(value) is str and _BRANCH.fullmatch(value) is not None


def _safe_url(url):
    return (type(url) is str and url.startswith('https://') and len(url) <= 500
            and not any(char in url for char in '\n\r\x00 @'))


def _hash(owner):
    return hashlib.sha256(owner.encode()).hexdigest()


def _uri(path):
    return Path(path).resolve().as_posix().replace('?', '%3F').replace('#', '%23')


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _version(conn):
    names = _tables(conn)
    if 'cf_schema_migration' not in names:
        if names & {'cf_task_queue_v1', 'cf_queue_audit_v1', 'cf_audit_chain_v1', 'cf_audit_chain_tip_v1'}:
            raise QueueBlocked('schema mismatch')
        return 0
    try:
        versions = [row[0] for row in conn.execute('SELECT version FROM cf_schema_migration ORDER BY version')]
    except sqlite3.Error:
        raise QueueBlocked('schema mismatch') from None
    if versions == [1] and {'cf_task_queue_v1', 'cf_queue_audit_v1', 'cf_audit_chain_v1', 'cf_audit_chain_tip_v1'} <= names:
        try:
            columns = {row[1] for row in conn.execute('PRAGMA table_info(cf_task_queue_v1)')}
            chain = {row[1] for row in conn.execute('PRAGMA table_info(cf_audit_chain_v1)')}
            tip = {row[1] for row in conn.execute('PRAGMA table_info(cf_audit_chain_tip_v1)')}
        except sqlite3.Error:
            raise QueueBlocked('schema mismatch') from None
        required = {'publish_branch', 'publish_commit', 'feedback_posts', 'feedback_at'}
        if not required <= columns:
            raise QueueBlocked('schema mismatch')
        if chain != {'seq', 'record_version', 'at_ms', 'event', 'task_id', 'state', 'fencing_token', 'detail', 'prev_hash', 'record_hash'}:
            raise QueueBlocked('schema mismatch')
        if tip != {'id', 'length', 'tip_hash'}:
            raise QueueBlocked('schema mismatch')
        return 1
    raise QueueBlocked('schema mismatch')


def _by_key(conn, key):
    return conn.execute(
        '''SELECT * FROM cf_task_queue_v1
           WHERE repo=? AND issue=? AND authorization_version=? AND trigger_key=?''',
        (key['repo'], key['issue'], key['authorization_version'], key['trigger'])).fetchone()


def _chain_event_name(event, state, detail):
    if event == 'heartbeat':
        return 'lease_renew'
    if event == 'interrupted' or detail == 'lease expired':
        return 'lease_expire'
    if event == 'claim' or (event == 'reserve' and state == 'claimed'):
        return 'claim'
    if state == 'publish_unknown' or detail == 'publish_unknown':
        return 'publish_unknown'
    if event == 'reconcile':
        return 'reconcile_result'
    if event == 'feedback_attempt':
        return 'feedback_retry'
    if event == 'fencing_reject':
        return 'fencing_reject'
    if event == 'breaker_latch':
        return 'breaker_latch'
    return 'state'


def _chain_detail(detail):
    if type(detail) is not str:
        return 'redacted'
    detail = _DETAIL_ALIAS.get(detail, detail)
    if detail in _DETAILS and '@' not in detail and '://' not in detail:
        return detail
    return 'redacted'


def _chain_hash(seq, at_ms, event, task_id, state, token, detail, prev):
    material = '|'.join((
        str(CHAIN_RECORD_VERSION), str(seq), str(at_ms), event,
        str(task_id), state, str(token), detail, prev,
    ))
    if not material.isascii() or any(char in material for char in '\n\r\x00'):
        raise QueueBlocked('audit chain failed')
    return hashlib.sha256(material.encode('ascii')).hexdigest()


def _chain_failure(kind, seq):
    return {'ok': False, 'kind': kind, 'seq': seq, 'records': []}


def verify_chain(conn):
    """Read the chain. The first broken record is the reported location."""
    try:
        tips = list(conn.execute('SELECT id, length, tip_hash FROM cf_audit_chain_tip_v1 ORDER BY id'))
        rows = list(conn.execute(
            '''SELECT seq, record_version, at_ms, event, task_id, state, fencing_token, detail, prev_hash, record_hash
               FROM cf_audit_chain_v1 ORDER BY seq'''))
    except sqlite3.Error:
        return _chain_failure('unreadable', 0)
    if len(tips) != 1 or tips[0][0] != 1:
        return _chain_failure('truncation', 0)
    length, tip_hash = tips[0][1], tips[0][2]
    if type(length) is not int or length < 0 or not _CHAIN_HASH.fullmatch(tip_hash or ''):
        return _chain_failure('tamper', 0)
    expected = 1
    for row in rows:
        seq = row[0]
        if type(seq) is not int or seq != expected:
            if type(seq) is int and seq > expected:
                return _chain_failure('deletion', expected)
            return _chain_failure('reorder', expected)
        expected += 1
    if length != len(rows):
        if length > len(rows):
            return _chain_failure('truncation', len(rows) + 1)
        return _chain_failure('tamper', length + 1)
    records = []
    previous = GENESIS
    for row in rows:
        seq, version, at_ms, event, task_id, state, token, detail, prev, digest = row
        if version != CHAIN_RECORD_VERSION or type(at_ms) is not int or not 0 <= at_ms <= 10**15:
            return _chain_failure('tamper', seq)
        if type(task_id) is not int or task_id < 0 or type(token) is not int or token < 0:
            return _chain_failure('tamper', seq)
        if event not in _CHAIN_EVENTS or state not in STATES or detail not in _DETAILS:
            return _chain_failure('tamper', seq)
        if not _CHAIN_HASH.fullmatch(prev or '') or not _CHAIN_HASH.fullmatch(digest or ''):
            return _chain_failure('tamper', seq)
        if prev != previous:
            return _chain_failure('reorder', seq)
        try:
            actual = _chain_hash(seq, at_ms, event, task_id, state, token, detail, prev)
        except QueueBlocked:
            return _chain_failure('tamper', seq)
        if actual != digest:
            return _chain_failure('tamper', seq)
        previous = digest
        records.append({
            'seq': seq,
            'record_version': version,
            'at_ms': at_ms,
            'event': event,
            'task_id': task_id,
            'state': state,
            'fencing_token': token,
            'detail': detail,
            'prev_hash': prev,
            'record_hash': digest,
        })
    if previous != tip_hash:
        where = rows[-1][0] if rows else 1
        return _chain_failure('truncation', where)
    return {'ok': True, 'kind': None, 'seq': None, 'records': records}


def read_chain_report(database):
    path = Path(database)
    if path.name == 'state.db' or path.is_symlink():
        raise QueueBlocked('queue database must not be the legacy ledger')
    if not path.is_file():
        return _chain_failure('unreadable', 0)
    try:
        header = path.read_bytes()[:16]
    except OSError:
        return _chain_failure('unreadable', 0)
    if header != _HEADER:
        return _chain_failure('unreadable', 0)
    uri = 'file:' + _uri(path) + '?mode=ro'
    try:
        conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    except sqlite3.Error:
        return _chain_failure('truncation', 0)
    try:
        try:
            check = conn.execute('PRAGMA integrity_check').fetchone()
            version = _version(conn)
        except QueueBlocked:
            return _chain_failure('unreadable', 0)
        except sqlite3.Error:
            return _chain_failure('truncation', 0)
        if check is None or check[0] != 'ok' or version != 1:
            return _chain_failure('truncation', 0)
        return verify_chain(conn)
    finally:
        conn.close()


def _next_attempt(conn, key):
    own = conn.execute('SELECT count(*) FROM cf_task_queue_v1 WHERE issue=?', (key['issue'],)).fetchone()[0]
    own_day = conn.execute('SELECT count(*) FROM cf_task_queue_v1 WHERE day=?', (key['day'],)).fetchone()[0]
    used = key['prior_attempts'] if key['prior_attempts'] > own else own
    used_day = key['prior_daily'] if key['prior_daily'] > own_day else own_day
    if used >= key['max_attempts'] or used_day >= key['max_daily']:
        raise QueueBlocked('attempt budget exhausted')
    return used + 1
