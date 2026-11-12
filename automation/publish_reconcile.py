"""Reconcile a GitHub write whose result is unknown.

Bounded retries for read-only GETs stay in GitHub.api. This module does not
sleep, does not open a socket, and does not repeat a create POST. The only
write it plans is a redacted feedback comment, after a read shows that the
feedback marker is absent and the persisted count is still under the cap.

CircuitBreaker.latch creates a file. Nothing here deletes or rewrites a file
that already exists. Clearing that file is a manual owner step.
"""
import base64
import os
from pathlib import Path
import re


FEEDBACK_MARKER = '<!-- cf-codex-feedback -->'
MAX_FEEDBACK_POSTS = 2
FEEDBACK_WINDOW_MS = 24 * 60 * 60 * 1000
REASONS = frozenset({
    'auth', 'branch_protection', 'policy', 'ledger',
    'duplicate_claim', 'unreconcilable_write', 'safety_test',
})
_BRANCH = re.compile(r'codex/issue-\d+-attempt-[12]-[0-9]+\Z')
_SHA = re.compile(r'[0-9a-f]{40}\Z')
_TRANSPORT = re.compile(r'GitHub [a-z]+ failure(?: HTTP (\d{3}))?; request stopped\Z')
_UNKNOWN_HTTP = frozenset({408, 429, 500, 502, 503, 504})
_REPO = 'yunyidamowang/contractorflow-studio'


class BreakerError(Exception):
    pass


class WriteFailed(Exception):
    """One create attempt finished without a proved acceptance."""

    def __init__(self, kind):
        if kind not in ('auth', 'unknown', 'rejected'):
            kind = 'unknown'
        self.kind = kind
        super().__init__('write result unknown')


class CircuitBreaker:
    """A file that, once written, stays until an owner deletes it."""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.name == 'state.db' or self.path.is_symlink():
            raise BreakerError('breaker path rejected')

    def reason(self):
        if self.path.is_symlink() or self.path.is_dir():
            return 'unreconcilable_write'
        if not self.path.exists():
            return None
        try:
            data = self.path.read_bytes()
        except OSError:
            return 'unreconcilable_write'
        if not data.endswith(b'\n') or data.count(b'\n') != 1:
            return 'unreconcilable_write'
        try:
            token = data[:-1].decode('ascii')
        except UnicodeError:
            return 'unreconcilable_write'
        if token not in REASONS:
            return 'unreconcilable_write'
        return token

    def latched(self):
        return self.reason() is not None

    def assert_closed(self):
        if self.latched():
            raise BreakerError('circuit breaker latched')

    def latch(self, reason):
        if reason not in REASONS:
            reason = 'unreconcilable_write'
        if self.path.is_symlink() or self.path.is_dir():
            raise BreakerError('breaker path rejected')
        if self.path.exists():
            return
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError:
            return
        except OSError:
            raise BreakerError('circuit breaker latched') from None
        try:
            os.write(fd, (reason + '\n').encode('ascii'))
            os.fsync(fd)
        except OSError:
            raise BreakerError('circuit breaker latched') from None
        finally:
            os.close(fd)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            raise BreakerError('circuit breaker latched') from None


def classify_blocked(message):
    """Classify one finished write. Does not issue a request or sleep."""
    if type(message) is not str:
        return 'unknown'
    match = _TRANSPORT.fullmatch(message)
    if match is None or match.group(1) is None:
        return 'unknown'
    status = int(match.group(1))
    if status in (401, 403):
        return 'auth'
    if status in _UNKNOWN_HTTP:
        return 'unknown'
    return 'rejected'


def transport_view(message):
    """Map one blocked GET message to (status, None), or None if undecided."""
    if type(message) is not str:
        return None
    match = _TRANSPORT.fullmatch(message)
    if match is None or match.group(1) is None:
        return None
    return (int(match.group(1)), None)


def observe_controls(repo, branch):
    """Return a breaker reason, or None when the public controls still match."""
    if not isinstance(repo, dict) or not isinstance(branch, dict):
        return 'unreconcilable_write'
    if repo.get('full_name') != _REPO or repo.get('private') is not False:
        return 'policy'
    if repo.get('allow_auto_merge') is not False:
        return 'policy'
    if branch.get('name') != 'main' or branch.get('protected') is not True:
        return 'branch_protection'
    return None


def _safe_url(url):
    return (type(url) is str and url.startswith('https://') and len(url) <= 500
            and not any(char in url for char in '\n\r\x00 @'))


def publish_draft(post, note_target, number, attempt, base, tree_sha, changes, branch):
    """Create blobs, a tree, a commit, one branch, and one draft PR.

    note_target runs after the commit sha is known and before the branch POST.
    post is called once per object. WriteFailed is not caught here, and this
    function does not call GET.
    """
    if type(number) is not int or attempt not in (1, 2) or not _BRANCH.fullmatch(branch or ''):
        raise WriteFailed('rejected')
    if not branch.startswith(f'codex/issue-{number}-attempt-{attempt}-'):
        raise WriteFailed('rejected')
    if not _SHA.fullmatch(base or '') or not _SHA.fullmatch(tree_sha or ''):
        raise WriteFailed('rejected')
    entries = []
    for item in changes:
        if type(item) is not tuple or len(item) != 3:
            raise WriteFailed('rejected')
        path, content, mode = item
        if type(path) is not str or type(content) is not bytes or mode not in ('100644', '100755'):
            raise WriteFailed('rejected')
        blob = post('/git/blobs', {
            'content': base64.b64encode(content).decode('ascii'),
            'encoding': 'base64',
        })
        sha = blob.get('sha') if isinstance(blob, dict) else None
        if type(sha) is not str or not _SHA.fullmatch(sha):
            raise WriteFailed('unknown')
        entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': sha})
    if not entries:
        raise WriteFailed('rejected')
    tree = post('/git/trees', {'base_tree': tree_sha, 'tree': entries})
    tree_id = tree.get('sha') if isinstance(tree, dict) else None
    if type(tree_id) is not str or not _SHA.fullmatch(tree_id):
        raise WriteFailed('unknown')
    commit = post('/git/commits', {
        'message': f'SAMPLE task #{number}, attempt {attempt}',
        'tree': tree_id,
        'parents': [base],
    })
    commit_id = commit.get('sha') if isinstance(commit, dict) else None
    if type(commit_id) is not str or not _SHA.fullmatch(commit_id):
        raise WriteFailed('unknown')
    note_target(branch, commit_id)
    post('/git/refs', {'ref': 'refs/heads/' + branch, 'sha': commit_id})
    pull = post('/pulls', {
        'base': 'main',
        'head': branch,
        'draft': True,
        'title': f'[Codex] SAMPLE task #{number} / attempt {attempt}',
        'body': (
            f'Relates to #{number}. Fixed test suite passed. Review diff and acceptance manually.\n'
            f'Base: {base}\nNo automatic merge or issue closure.'
        ),
    })
    url = pull.get('html_url') if isinstance(pull, dict) else None
    if not _safe_url(url):
        raise WriteFailed('unknown')
    return url, commit_id


def decide_publish(ref, pulls, commit_view, branch, commit):
    """Return (outcome, url). Outcomes: exists, absent, partial, unknown, auth.

    A None view means that read could not be decided. No create is implied.
    """
    views = (ref, pulls, commit_view)
    if any(view is None for view in views):
        return 'unknown', None
    if any(not isinstance(view, tuple) or len(view) != 2 or type(view[0]) is not int for view in views):
        return 'unknown', None
    if any(view[0] in (401, 403) for view in views):
        return 'auth', None
    if any(view[0] not in (200, 404) for view in views):
        return 'unknown', None
    branch_match = ref[0] == 200 and _ref_sha(ref[1]) == commit
    branch_absent = ref[0] == 404
    commit_match = (commit_view[0] == 200 and isinstance(commit_view[1], dict)
                    and commit_view[1].get('sha') == commit)
    matched = _matching_pulls(pulls, branch, commit)
    if matched is None:
        return 'unknown', None
    if branch_match and commit_match and len(matched) == 1:
        return 'exists', matched[0]
    if branch_absent and len(matched) == 0:
        return 'absent', None
    if branch_match and len(matched) == 0:
        return 'partial', None
    return 'unknown', None


def _ref_sha(body):
    if not isinstance(body, dict):
        return None
    obj = body.get('object')
    if not isinstance(obj, dict):
        return None
    sha = obj.get('sha')
    if type(sha) is str and _SHA.fullmatch(sha):
        return sha
    return None


def _matching_pulls(pulls, branch, commit):
    if pulls[0] != 200 or not isinstance(pulls[1], list):
        return None
    found = []
    for item in pulls[1]:
        if not isinstance(item, dict):
            return None
        head = item.get('head') if isinstance(item.get('head'), dict) else None
        if head is None or head.get('ref') != branch:
            continue
        base = item.get('base') if isinstance(item.get('base'), dict) else {}
        url = item.get('html_url')
        if (head.get('sha') == commit and base.get('ref') == 'main'
                and item.get('draft') is True and _safe_url(url)):
            found.append(url)
            continue
        return None
    return found


def marker_present(comments, marker):
    """True, False, or None when the comment list cannot be trusted."""
    if type(marker) is not str or not marker or not isinstance(comments, list):
        return None
    found = False
    for item in comments:
        if not isinstance(item, dict):
            return None
        body = item.get('body')
        if type(body) is not str:
            return None
        if marker in body:
            found = True
    return found


def feedback_body(url, files, attempt):
    if not _safe_url(url) or attempt not in (1, 2):
        raise WriteFailed('rejected')
    names = []
    for name in files:
        if (type(name) is str and re.fullmatch(r'[A-Za-z0-9_./-]+', name)
                and '..' not in name.split('/') and len(name) <= 120):
            names.append(name)
    shown = ', '.join(names) if names else 'see the draft PR'
    if len(shown) > 500:
        shown = 'see the draft PR'
    return (
        FEEDBACK_MARKER + '\n'
        + f'Draft PR: {url}\nFixed unittest suite: PASS. Files: {shown}\n'
        + f'Attempt {attempt}/2. Manual acceptance required. Raw logs stay local; '
        + 'Goal/Acceptance must be reviewed in PR.'
    )
