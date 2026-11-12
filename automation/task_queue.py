"""Single-machine task queue. Not distributed mutual exclusion.

Two processes on one machine are excluded by a local flock plus a SQLite
BEGIN IMMEDIATE transaction. A second machine, a copied database, or a
clock we cannot trust is fail-closed. An expired lease is interrupted for
review; it is not a second model run. Attempt rows are not deleted or
refunded. This module does not migrate a database unless migrate_up or
migrate_down is called, and it refuses a file named state.db.
"""
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time


STATES = frozenset({
    'queued', 'claimed', 'snapshot', 'model', 'testing', 'publishing',
    'feedback_pending', 'review', 'blocked', 'stopped', 'interrupted',
})
TERMINAL = frozenset({'review', 'blocked', 'stopped', 'interrupted'})
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

    def close_as(self, state, now=None):
        if state not in ('blocked', 'stopped'):
            raise QueueBlocked('close state rejected')
        now = self.queue._now(now)
        with self.queue._exclusive() as conn:
            row = self._row(conn)
            # feedback_pending means the publish was recorded. Do not turn that into a rerunnable failure.
            if row['state'] not in {'claimed', 'snapshot', 'model', 'testing', 'publishing'} or not self._matches(row):
                return self
            if type(row['reserved_at']) is not int or now < row['reserved_at']:
                self.queue._terminal(conn, row, 'blocked', now, 'clock moved backwards')
                return self
            self.queue._terminal(conn, row, state, now, 'closed')
        return self

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
            raise QueueFenced('fencing token rejected')
        if type(row['reserved_at']) is not int or now < row['reserved_at']:
            self.queue._terminal(conn, row, 'blocked', now, 'clock moved backwards')
            raise _CommitAndRaise(QueueBlocked('clock moved backwards'))
        if type(row['lease_until']) is not int or now >= row['lease_until']:
            self.queue._terminal(conn, row, 'interrupted', now, 'lease expired', event='interrupted')
            raise _CommitAndRaise(QueueFenced('lease expired'))
        if row['state'] not in allowed:
            raise QueueFenced('fencing token rejected')
        return row


class Queue:
    def __init__(self, database, *, lock_path=None, lease_ms=120_000, heartbeat_ms=30_000, clock=None):
        self.database = Path(database)
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
                    'INSERT INTO cf_schema_migration(version, name, applied_at) VALUES (1, ?, ?)',
                    ('cf_task_queue_v1', 'explicit'))
                conn.commit()
            except QueueBlocked:
                conn.rollback()
                raise
            except sqlite3.Error:
                conn.rollback()
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
                conn.execute('DROP TABLE cf_queue_audit_v1')
                conn.execute('DROP TABLE cf_task_queue_v1')
                conn.execute('DROP TABLE cf_schema_migration')
                conn.commit()
            except QueueBlocked:
                conn.rollback()
                raise
            except sqlite3.Error:
                conn.rollback()
                raise QueueBlocked('queue database corrupt') from None
        finally:
            if conn is not None:
                conn.close()
            self._release_lock(fd)

    def enqueue(self, *, repo, issue, authorization_version, trigger, day, max_attempts, max_daily,
                prior_attempts=0, prior_daily=0, now=None):
        """Persist a queued attempt. Does not claim it and does not start a model."""
        key = self._key(repo, issue, authorization_version, trigger, day, max_attempts, max_daily, prior_attempts, prior_daily)
        now = self._now(now)
        with self._exclusive() as conn:
            if _by_key(conn, key) is not None:
                raise QueueBlocked('duplicate claim')
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
        key = self._identity(repo, issue, authorization_version, trigger)
        now = self._now(now)
        with self._exclusive() as conn:
            row = _by_key(conn, key)
            if row is None or row['state'] != 'queued' or row['owner_hash'] is not None:
                raise QueueBlocked('duplicate claim')
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
        key = self._key(repo, issue, authorization_version, trigger, day, max_attempts, max_daily, prior_attempts, prior_daily)
        now = self._now(now)
        with self._exclusive() as conn:
            if _by_key(conn, key) is not None:
                raise QueueBlocked('duplicate claim')
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
                if row['state'] in TERMINAL:
                    continue
                if type(row['reserved_at']) is not int or now < row['reserved_at']:
                    self._terminal(conn, row, 'blocked', now, 'clock moved backwards')
                    raise _CommitAndRaise(QueueBlocked('clock moved backwards'))
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

    def audit_export(self):
        with self._exclusive() as conn:
            rows = conn.execute(
                'SELECT id, task_id, event, state, fencing_token, at_ms, detail '
                'FROM cf_queue_audit_v1 ORDER BY id').fetchall()
            return [
                (row['id'], row['task_id'], row['event'], row['state'], row['fencing_token'], row['at_ms'], row['detail'])
                for row in rows]

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

    def _assert_header(self):
        if self.database.name == 'state.db' or self.database.is_symlink():
            raise QueueBlocked('queue database must not be the legacy ledger')
        if not self.database.is_file():
            raise QueueBlocked('queue database missing')
        try:
            with self.database.open('rb') as handle:
                header = handle.read(16)
        except OSError:
            raise QueueBlocked('queue database unreadable') from None
        if header != _HEADER:
            raise QueueBlocked('queue database corrupt')

    def _read_only_check(self):
        self._assert_header()
        uri = 'file:' + _uri(self.database) + '?mode=ro'
        try:
            ro = sqlite3.connect(uri, uri=True, isolation_level=None)
        except sqlite3.Error:
            raise QueueBlocked('queue database corrupt') from None
        try:
            try:
                check = ro.execute('PRAGMA integrity_check').fetchone()
                version = _version(ro)
            except sqlite3.Error:
                raise QueueBlocked('queue database corrupt') from None
        finally:
            ro.close()
        if check is None or check[0] != 'ok':
            raise QueueBlocked('queue database corrupt')
        if version != 1:
            raise QueueBlocked('schema mismatch')

    def _open_checked(self):
        self._read_only_check()
        try:
            conn = sqlite3.connect(self.database, isolation_level=None, timeout=5)
        except sqlite3.Error:
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


def _hash(owner):
    return hashlib.sha256(owner.encode()).hexdigest()


def _uri(path):
    return Path(path).resolve().as_posix().replace('?', '%3F').replace('#', '%23')


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _version(conn):
    names = _tables(conn)
    if 'cf_schema_migration' not in names:
        if 'cf_task_queue_v1' in names or 'cf_queue_audit_v1' in names:
            raise QueueBlocked('schema mismatch')
        return 0
    try:
        versions = [row[0] for row in conn.execute('SELECT version FROM cf_schema_migration ORDER BY version')]
    except sqlite3.Error:
        raise QueueBlocked('schema mismatch') from None
    if versions == [1] and {'cf_task_queue_v1', 'cf_queue_audit_v1'} <= names:
        return 1
    raise QueueBlocked('schema mismatch')


def _by_key(conn, key):
    return conn.execute(
        '''SELECT * FROM cf_task_queue_v1
           WHERE repo=? AND issue=? AND authorization_version=? AND trigger_key=?''',
        (key['repo'], key['issue'], key['authorization_version'], key['trigger'])).fetchone()


def _next_attempt(conn, key):
    own = conn.execute('SELECT count(*) FROM cf_task_queue_v1 WHERE issue=?', (key['issue'],)).fetchone()[0]
    own_day = conn.execute('SELECT count(*) FROM cf_task_queue_v1 WHERE day=?', (key['day'],)).fetchone()[0]
    used = key['prior_attempts'] if key['prior_attempts'] > own else own
    used_day = key['prior_daily'] if key['prior_daily'] > own_day else own_day
    if used >= key['max_attempts'] or used_day >= key['max_daily']:
        raise QueueBlocked('attempt budget exhausted')
    return used + 1
