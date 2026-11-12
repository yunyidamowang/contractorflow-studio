"""Prove a legacy ledger's rows survive a queue migration on a copy.

The source is opened read-only. Migration runs only on the copy and is
reversed there. A file named state.db is refused unless fixture=True.
A path inside .automation is always refused. This module does not claim
that the original file's whole-file hash stays the same: SQLite rewrites
pages when tables are added. The proof is the exported row values and the
attempt count.
"""
import hashlib
import sqlite3
from pathlib import Path

from automation.task_queue import Queue, QueueBlocked


class LedgerProofError(Exception):
    pass


def prove_legacy_rows(source, destination_dir, *, fixture=False):
    """Back up source, export its runs and notices, and migrate only the copy.

    Returns a report. Does not write the source. Does not enable a dispatcher.
    """
    source = Path(source)
    destination = Path(destination_dir)
    if source.is_symlink() or destination.is_symlink():
        raise LedgerProofError('refusing symlink')
    if not source.is_file() or not destination.is_dir():
        raise LedgerProofError('ledger proof paths rejected')
    if _live_ledger(source):
        raise LedgerProofError('refusing live ledger')
    if source.name == 'state.db' and fixture is not True:
        raise LedgerProofError('refusing state.db')
    before = _read_bytes(source)
    export = _export_legacy(source)
    counts = _attempt_counts(source)
    copy = destination / 'ledger-copy.db'
    if copy.name == 'state.db' or copy.exists() or copy.is_symlink():
        raise LedgerProofError('ledger copy rejected')
    _backup(source, copy)
    copy_before = hashlib.sha256(copy.read_bytes()).hexdigest()
    export_path = destination / 'legacy-rows.txt'
    export_path.write_bytes(export)
    try:
        queue = Queue(copy)
        queue.migrate_up()
        after_up = _export_legacy(copy)
        counts_up = _attempt_counts(copy)
        if after_up != export or counts_up != counts:
            raise LedgerProofError('legacy rows changed')
        queue.migrate_down()
        after_down = _export_legacy(copy)
        if after_down != export or _attempt_counts(copy) != counts:
            raise LedgerProofError('legacy rows changed')
        if _table_names(copy) != _table_names_from_export_db(source):
            raise LedgerProofError('migration was not reversed')
        queue.migrate_up()
        if _export_legacy(copy) != export or _attempt_counts(copy) != counts:
            raise LedgerProofError('legacy rows changed')
    except QueueBlocked as exc:
        raise LedgerProofError('ledger proof failed closed') from exc
    if _read_bytes(source) != before:
        raise LedgerProofError('source was modified')
    copy_after = hashlib.sha256(copy.read_bytes()).hexdigest()
    return {
        'ok': True,
        'attempt_count_before': counts['runs'],
        'attempt_count_after': counts_up['runs'],
        'per_issue_before': counts['per_issue'],
        'per_issue_after': counts_up['per_issue'],
        'row_export_unchanged': True,
        'reversible': True,
        'source_bytes_unchanged': True,
        'copy_file_hash_before': copy_before,
        'copy_file_hash_after_up': copy_after,
        'copy_file_hash_changed': copy_before != copy_after,
        'whole_file_hash_is_not_the_proof': True,
        'export_path': export_path.name,
        'backup_path': copy.name,
    }


def _live_ledger(path):
    return '.automation' in Path(path).resolve().parts


def _read_bytes(path):
    try:
        return path.read_bytes()
    except OSError:
        raise LedgerProofError('ledger unreadable') from None


def _connect_ro(path):
    if Path(path).is_symlink():
        raise LedgerProofError('refusing symlink')
    uri = 'file:' + Path(path).resolve().as_posix().replace('?', '%3F').replace('#', '%23') + '?mode=ro'
    try:
        return sqlite3.connect(uri, uri=True, isolation_level=None)
    except sqlite3.Error:
        raise LedgerProofError('ledger unreadable') from None


def _backup(source, copy):
    src = _connect_ro(source)
    try:
        dst = sqlite3.connect(copy, isolation_level=None)
        try:
            src.backup(dst)
        except sqlite3.Error:
            raise LedgerProofError('backup failed') from None
        finally:
            dst.close()
    finally:
        src.close()
    if not copy.is_file() or copy.is_symlink():
        raise LedgerProofError('backup failed')


def _require_legacy(conn):
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'runs', 'notices'} <= names:
        raise LedgerProofError('legacy tables missing')
    return names


def _export_legacy(path):
    conn = _connect_ro(path)
    try:
        _require_legacy(conn)
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


def _attempt_counts(path):
    conn = _connect_ro(path)
    try:
        _require_legacy(conn)
        total = conn.execute('SELECT count(*) FROM runs').fetchone()[0]
        per_issue = tuple(conn.execute(
            'SELECT issue, count(*) FROM runs GROUP BY issue ORDER BY issue').fetchall())
        return {'runs': total, 'per_issue': per_issue}
    finally:
        conn.close()


def _table_names(path):
    conn = _connect_ro(path)
    try:
        return tuple(row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
    finally:
        conn.close()


def _table_names_from_export_db(path):
    return _table_names(path)
