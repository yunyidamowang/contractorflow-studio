"""Opt-in local Issue worker. Only the supervisor holds GitHub credentials.

python -m automation.dispatcher init|doctor|once|watch|stop|simulate
"""
import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import ssl
import http.client
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.automation'
REPO = 'yunyidamowang/contractorflow-studio'
MARKER = '<!-- cf-codex-worker -->'
PROTECTED = {'AGENTS.md', 'SECURITY.md', 'HANDOFF.md', 'DECISIONS.md', 'requirements.txt', '.gitignore'}
MAX_PATCH = 200_000


class Blocked(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None  # Never forward the repository token to a redirected destination.


def allowed_path(path):
    if not isinstance(path, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', path):
        return False
    p = PurePosixPath(path)
    return (not p.is_absolute() and all(x not in ('.', '..') and not x.startswith('.') for x in path.split('/'))
            and path not in PROTECTED and path not in ('tests/test_automation.py',)
            and not path.startswith('tests/')
            and (path.startswith(('app/', 'docs/')) or path in ('README.md', 'DEMO_WALKTHROUGH.md', 'TRIAL_SCOPE.md')))


def parse_task(issue, comments):
    body = issue.get('body') or ''
    if len(body) > 20_000 or '\x00' in body:
        raise Blocked('Task body exceeds the safe input limit')
    fields = {}
    for name in ('Goal', 'Acceptance', 'Allowed paths', 'References'):
        match = re.search(r'^## '+re.escape(name)+r'\s*\n(.*?)(?=^## |\Z)', body, re.M | re.S)
        if not match or not match[1].strip():
            raise Blocked('Missing structured section: '+name)
        fields[name] = match[1].strip()
    paths = [line.strip().removeprefix('- ').strip('`') for line in fields['Allowed paths'].splitlines() if line.strip()]
    if not 1 <= len(paths) <= 10 or not all(allowed_path(p) for p in paths):
        raise Blocked('Allowed paths must be 1–10 explicit app/tests/docs files; protected files cannot change')
    return {'number': int(issue['number']), 'title': str(issue['title'])[:200], 'sections': fields,
            'allowed_paths': paths, 'comments_untrusted': [str(c.get('body', ''))[:4000] for c in comments[-10:]]}


def actor_gate(issue, events, actors):
    labels = {x['name'] for x in issue.get('labels', [])}
    if issue.get('state') != 'open' or 'pull_request' in issue or 'codex-ready' not in labels or 'codex-stop' in labels:
        raise Blocked('Issue is not an open, ready, non-stopped task')
    if issue.get('user', {}).get('login') not in actors:
        raise Blocked('Issue author is not allowlisted')
    last = next((e for e in reversed(events) if e.get('event') in ('labeled', 'unlabeled') and e.get('label', {}).get('name') == 'codex-ready'), None)
    if not last or last['event'] != 'labeled' or last.get('actor', {}).get('login') not in actors:
        raise Blocked('Ready-label actor is not allowlisted')
    return str(last['id'])


class GitHub:
    def __init__(self, token):
        self.token = token.strip()
        self.deadline = None
        if not self.token:
            raise Blocked('Project-scoped GitHub token missing')

    def api(self, method, route, data=None):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise Blocked('Total task deadline reached')
        # No arbitrary URLs, delete, merge, main ref updates, workflow or admin API.
        read = r'(?:|/issues(?:\?[^#]*)?|/issues/\d+(?:/(?:comments|events))?(?:\?[^#]*)?|/git/ref/heads/main|/git/commits/[0-9a-f]{40}|/git/trees/[0-9a-f]{40}(?:\?recursive=1)?|/git/blobs/[0-9a-f]{40}|/pulls\?[^#]*)'
        write = r'(?:/issues/\d+/comments|/git/(?:blobs|trees|commits|refs)|/pulls)'
        if not ((method == 'GET' and re.fullmatch(read, route)) or (method == 'POST' and re.fullmatch(write, route))):
            raise Blocked('GitHub operation outside worker capability')
        if route == '/git/refs' and not re.fullmatch(r'refs/heads/codex/issue-\d+-attempt-[12]-[0-9]+', data.get('ref', '')):
            raise Blocked('Only new codex task branches can be created')
        if route == '/pulls' and (data.get('base') != 'main' or data.get('draft') is not True):
            raise Blocked('Only draft PRs to main are allowed')
        request = urllib.request.Request('https://api.github.com/repos/'+REPO+route,
            data=None if data is None else json.dumps(data).encode(), method=method,
            headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'contractorflow-controlled-worker'})
        for attempt in range(1, 4 if method == 'GET' else 2):
            remaining = 20 if self.deadline is None else min(20, self.deadline-time.monotonic())
            if remaining <= 0 or stopped():
                raise Blocked('Task deadline or STOP reached')
            try:
                with urllib.request.build_opener(NoRedirect()).open(request, timeout=remaining) as response:
                    raw = response.read(12_000_001)
                    if self.deadline is not None and time.monotonic() >= self.deadline:
                        raise Blocked('Total task deadline reached')
                    if len(raw) > 12_000_000:
                        raise Blocked('GitHub response too large')
                    return json.loads(raw)
            except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, http.client.IncompleteRead) as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
                category = ('http' if status else 'dns' if isinstance(reason, socket.gaierror)
                            else 'tls' if isinstance(reason, ssl.SSLError)
                            else 'timeout' if isinstance(reason, TimeoutError) else 'connection')
                retry = method == 'GET' and attempt < 3 and (status is None or status in (408, 500, 502, 503, 504))
                if isinstance(reason, ssl.SSLCertVerificationError):
                    retry = False
                # Never serialize exception text, URLs, headers or request/response bodies.
                audit('github_network_error', method=method, category=category,
                      status=status, attempt=attempt, retry=retry)
                if not retry:
                    raise Blocked('GitHub '+category+' failure'+(' HTTP '+str(status) if status else '')+'; request stopped') from None
                delay = 0.5 * 2**(attempt-1)
                if self.deadline is not None and time.monotonic()+delay >= self.deadline:
                    raise Blocked('Total task deadline reached') from None
                time.sleep(delay)

    def pages(self, route):
        rows = []
        for page in range(1, 11):
            data = self.api('GET', route+('&' if '?' in route else '?')+f'per_page=100&page={page}')
            rows.extend(data)
            if len(data) < 100:
                return rows
        raise Blocked('Too many GitHub records; manual review required')

    def feedback(self, number, message):
        return self.api('POST', f'/issues/{number}/comments', {'body': MARKER+'\n'+message+'\nNo auto-merge. SAMPLE tasks only.'})

    def snapshot(self, checkout):
        if checkout.is_symlink() or not checkout.is_dir() or any(checkout.iterdir()):
            raise Blocked('Snapshot requires an empty real directory')
        repo = self.api('GET', '')
        if repo.get('full_name') != REPO or repo.get('private') is not False:
            raise Blocked('Snapshot repository identity mismatch')
        ref = self.api('GET', '/git/ref/heads/main')['object']['sha']
        commit = self.api('GET', '/git/commits/'+ref)
        if commit.get('sha') != ref:
            raise Blocked('Commit identity mismatch')
        tree_sha = commit['tree']['sha']
        tree = self.api('GET', '/git/trees/'+tree_sha+'?recursive=1')
        if tree.get('truncated') or len(tree['tree']) > 500:
            raise Blocked('Repository snapshot exceeds bounded size')
        if tree.get('sha') != tree_sha:
            raise Blocked('Tree identity mismatch')
        size = 0
        pending = []
        cache = {}
        seen = set()
        for entry in tree['tree']:
            path = PurePosixPath(entry['path'])
            if (entry['path'] in seen or str(path) != entry['path'] or not path.parts
                    or path.is_absolute() or '..' in path.parts or '\x00' in entry['path']
                    or path.parts[0] in ('.codex', '.agents', '.automation', '.git', 'data', 'backups')):
                raise Blocked('Unsafe snapshot path')
            seen.add(entry['path'])
            if entry['type'] == 'tree':
                continue
            if (entry['type'] != 'blob' or entry['mode'] not in ('100644', '100755') or path.is_absolute()
                    or '..' in path.parts or path.parts[0] in ('.codex', '.agents', '.automation', '.git', 'data', 'backups')):
                raise Blocked('Unsafe snapshot entry')
            if type(entry.get('size')) is not int or entry['size'] < 0:
                raise Blocked('Invalid snapshot file size')
            size += entry['size']
            if size > 5_000_000:
                raise Blocked('Repository snapshot exceeds 5 MB')
            if entry['sha'] not in cache:
                blob = self.api('GET', '/git/blobs/'+entry['sha'])
                if blob.get('sha') != entry['sha'] or blob.get('encoding') != 'base64':
                    raise Blocked('Blob identity mismatch')
                content = base64.b64decode(''.join(blob['content'].split()), validate=True)
                actual = hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
                if actual != entry['sha'] or blob.get('size') != len(content):
                    raise Blocked('Blob hash or size mismatch')
                cache[entry['sha']] = content
            content = cache[entry['sha']]
            if len(content) != entry.get('size', len(content)):
                raise Blocked('Snapshot blob size mismatch')
            pending.append((path, content, entry['mode']))
        # Reconstruct every Git tree, including mode and filename ordering.
        def verify_tree(parent, expected):
            children = [e for e in tree['tree'] if str(PurePosixPath(e['path']).parent) == parent]
            raw = b''
            for e in sorted(children, key=lambda e: (PurePosixPath(e['path']).name+('/' if e['type']=='tree' else '')).encode()):
                if e['type'] == 'tree':
                    if e['mode'] != '040000':
                        raise Blocked('Invalid tree mode')
                    verify_tree(e['path'], e['sha'])
                raw += e['mode'].lstrip('0').encode()+b' '+PurePosixPath(e['path']).name.encode()+b'\0'+bytes.fromhex(e['sha'])
            if hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != expected:
                raise Blocked('Git tree hash mismatch')
        directories = {e['path'] for e in tree['tree'] if e['type'] == 'tree'}
        if any(str(PurePosixPath(e['path']).parent) not in directories | {'.'} for e in tree['tree']):
            raise Blocked('Snapshot contains an orphan entry')
        verify_tree('.', tree_sha)
        if stopped() or (self.deadline is not None and time.monotonic() >= self.deadline):
            raise Blocked('Task deadline or STOP reached')
        for path, content, mode in pending:
            target = checkout / str(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(int(mode[-3:], 8))
        return ref, tree_sha

    def publish(self, number, attempt, base, tree_sha, changes):
        entries = []
        for path, content, mode in changes:
            blob = self.api('POST', '/git/blobs', {'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
            entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': blob['sha']})
        tree = self.api('POST', '/git/trees', {'base_tree': tree_sha, 'tree': entries})
        commit = self.api('POST', '/git/commits', {'message': f'SAMPLE task #{number}, attempt {attempt}', 'tree': tree['sha'], 'parents': [base]})
        branch = f'codex/issue-{number}-attempt-{attempt}-{time.time_ns()}'
        self.api('POST', '/git/refs', {'ref': 'refs/heads/'+branch, 'sha': commit['sha']})
        return self.api('POST', '/pulls', {'base': 'main', 'head': branch, 'draft': True,
            'title': f'[Codex] SAMPLE task #{number} / attempt {attempt}',
            'body': f'Relates to #{number}. Fixed test suite passed. Review diff and acceptance manually.\nBase: {base}\nNo automatic merge or issue closure.'})['html_url']


def settings():
    config = json.loads((RUNTIME / 'settings.json').read_text())
    config.setdefault('canary_issue', 4)
    if config['canary_issue'] is not None and (type(config['canary_issue']) is not int or config['canary_issue'] < 1):
        raise Blocked('Canary must be a positive Issue number or null after manual acceptance')
    for key, minimum, maximum in [('max_attempts_per_issue', 1, 2), ('max_runs_per_day', 1, 3),
            ('timeout_seconds', 30, 600), ('test_timeout_seconds', 30, 180), ('poll_seconds', 60, 3600), ('retry_delay_seconds', 60, 86400)]:
        if type(config.get(key)) is not int or not minimum <= config[key] <= maximum:
            raise Blocked('Invalid bounded setting: '+key)
    if type(config.get('enabled')) is not bool or not config.get('allowed_actors'):
        raise Blocked('Invalid activation/actor settings')
    return config


def stopped():
    return (RUNTIME / 'STOP').exists()


def audit(event, **values):
    # Metadata only: task text, model logs, credentials and test output stay local.
    with (RUNTIME / 'audit.jsonl').open('a') as stream:
        stream.write(json.dumps({'time': dt.datetime.now(dt.timezone.utc).isoformat(), 'event': event, **values})+'\n')


def clean_env(home, tmp):
    return {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(home),
            'CODEX_HOME': str(RUNTIME / 'codex-home'), 'TMPDIR': str(tmp), 'LANG': 'en_US.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}


def child(args, checkout, timeout, log, env, remote_stop=None):
    if stopped():
        raise Blocked('STOP switch active')
    with log.open('wb') as stream:
        process = subprocess.Popen(args, cwd=checkout, env=env, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        start = last_remote = time.monotonic()
        try:
            while process.poll() is None:
                if stopped() or time.monotonic()-start > timeout or log.stat().st_size > 2_000_000:
                    raise Blocked('Worker stopped, timed out or exceeded log limit')
                if remote_stop and time.monotonic()-last_remote > 30:
                    last_remote = time.monotonic()
                    if remote_stop():
                        raise Blocked('Remote stop label or ready removal')
                time.sleep(.25)
            if process.returncode:
                raise Blocked(f'Subprocess failed ({process.returncode}); local log: {log.name}')
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def git(checkout, *args):
    return subprocess.check_output(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', *args], cwd=checkout,
        env=clean_env(checkout / '.worker-tmp', checkout / '.worker-tmp'), stderr=subprocess.DEVNULL, timeout=30).decode().strip()


def prepare(checkout):
    (checkout / '.worker-tmp').mkdir()
    git(checkout, 'init', '-q')
    (checkout / '.git/info/exclude').write_text('.worker-tmp/\n')
    git(checkout, 'add', '.')
    git(checkout, '-c', 'user.name=Codex sample worker', '-c', 'user.email=codex-worker@users.noreply.github.com', 'commit', '-qm', 'Isolated trusted base')


def diff(checkout, paths):
    git(checkout, 'add', '--all')
    names = git(checkout, 'diff', '--cached', '--name-only', '-z').strip('\0').split('\0')
    if not names or names == ['']:
        raise Blocked('No patch produced; inspect local Codex log')
    if len(names) > 10:
        raise Blocked('Patch exceeds file count limit')
    changes = []
    for name in names:
        target = checkout / name
        if name not in paths or not allowed_path(name) or target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(checkout.resolve()):
            raise Blocked('Patch changes protected/unrequested paths, removes files or adds symlinks')
        status = git(checkout, 'diff', '--cached', '--name-status', '--', name).split('\t')[0]
        if status not in ('A', 'M'):
            raise Blocked('Only regular-file additions/modifications are allowed')
        raw = target.read_bytes()
        raw.decode('utf-8')
        mode = git(checkout, 'ls-files', '--stage', '--', name).split()[0]
        if mode not in ('100644', '100755'):
            raise Blocked('Unsupported file mode')
        changes.append((name, raw, mode))
    if sum(len(x[1]) for x in changes) > MAX_PATCH:
        raise Blocked('Patch exceeds 200 KB limit')
    return changes


def reserve(db, number, trigger, config):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    rows = db.execute('SELECT trigger,status,started FROM runs WHERE issue=? ORDER BY id DESC', (number,)).fetchall()
    if any(r[0] == trigger and r[1] in ('pr', 'running', 'blocked') for r in rows):
        raise Blocked('Trigger already handled; running/blocked tasks require manual review')
    if len(rows) >= config['max_attempts_per_issue']:
        raise Blocked('Issue lifetime attempt limit reached')
    if rows and time.time()-rows[0][2] < config['retry_delay_seconds']:
        raise Blocked('Retry cooldown active')
    count = db.execute('SELECT count(*) FROM runs WHERE day=?', (today,)).fetchone()[0]
    if count >= config['max_runs_per_day']:
        raise Blocked('Daily run limit reached')
    attempt = len(rows)+1
    cursor = db.execute('INSERT INTO runs(issue,trigger,status,started,day) VALUES(?,?,?,?,?)', (number, trigger, 'running', time.time(), today))
    db.commit()  # Durable reservation BEFORE snapshot/model/network side effects.
    return cursor.lastrowid, attempt


def profile():
    # Explicit profile; never inherits the user's global model/MCP/skills settings.
    venv = str((ROOT / '.venv').resolve())
    return '''forced_login_method = "chatgpt"
cli_auth_credentials_store = "file"
approval_policy = "never"
default_permissions = "contractorflow"
web_search = "disabled"
[permissions.contractorflow]
extends = ":workspace"
[permissions.contractorflow.filesystem]
":root" = "deny"
":minimal" = "read"
":tmpdir" = "deny"
":slash_tmp" = "deny"
"/opt/homebrew" = "read"
'''+json.dumps(venv)+''' = "read"
[permissions.contractorflow.filesystem.":workspace_roots"]
"." = "write"
".git" = "read"
".codex" = "deny"
".automation" = "deny"
[permissions.contractorflow.network]
enabled = false
'''


def initialize():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    RUNTIME.chmod(0o700)
    (RUNTIME / 'codex-home').mkdir(mode=0o700, exist_ok=True)
    config = RUNTIME / 'settings.json'
    if not config.exists():
        shutil.copyfile(ROOT / 'automation/settings.example.json', config)
    (RUNTIME / 'codex-home/config.toml').write_text(profile())
    (RUNTIME / 'codex-home/config.toml').chmod(0o600)


def sandbox(checkout, command):
    return ['codex', 'sandbox', '-P', 'contractorflow', '-C', str(checkout), '--', *command]


def preflight(checkout, logdir):
    tmp = checkout / '.worker-tmp'
    env = clean_env(tmp, tmp)
    forbidden = logdir / 'outside-canary.txt'
    forbidden.write_text('synthetic canary; not a private file')
    # Assert denied read/write, credential path, git protection, network and clean env.
    probe = '''import os,pathlib,socket
p=pathlib.Path('sandbox-write-probe.txt');p.write_text('sample');p.unlink()
for p in [pathlib.Path(%r),pathlib.Path(%r)]:
 try:p.read_text()
 except PermissionError:pass
 else:raise AssertionError('outside read allowed')
try:pathlib.Path('.git/config').write_text('blocked')
except PermissionError:pass
else:raise AssertionError('git write allowed')
assert 'GITHUB_TOKEN' not in os.environ and 'OPENAI_API_KEY' not in os.environ
s=socket.socket();s.settimeout(1)
try:s.connect(('1.1.1.1',443))
except PermissionError:pass
else:raise AssertionError('network allowed or inconclusive')
print('PASS isolation: checkout write, outside read denied, auth-root denied, git protected, network denied')
''' % (str(forbidden), str(RUNTIME / 'codex-home/config.toml'))
    child(sandbox(checkout, [sys.executable, '-c', probe]), checkout, 30, logdir / 'isolation.log', env)


def verify_test_result(test_log, policy):
    try:
        records = [json.loads(line.removeprefix('CF_TEST_RESULT '))
                   for line in test_log.splitlines() if line.startswith('CF_TEST_RESULT ')]
        if (len(records) != 1 or not isinstance(records[0], dict)
                or records[0].get('success') is not True
                or type(records[0].get('count')) is not int
                or records[0]['count'] != len(policy['tests'])
                or records[0].get('tests') != sorted(policy['tests'])):
            raise ValueError('mismatch')
    except (ValueError, TypeError, KeyError):
        raise Blocked('Trusted test manifest/result mismatch') from None


def run_issue(api, issue, config, db):
    number = int(issue['number'])
    events = api.pages(f'/issues/{number}/events')
    trigger = actor_gate(issue, events, config['allowed_actors'])
    comments = [c for c in api.pages(f'/issues/{number}/comments') if c.get('user', {}).get('login') in config['allowed_actors'] and MARKER not in c.get('body', '')]
    task = parse_task(issue, comments)
    # Re-read before reserving to avoid running a stale poll result after revocation.
    actor_gate(api.api('GET', f'/issues/{number}'), api.pages(f'/issues/{number}/events'), config['allowed_actors'])
    rowid, attempt = reserve(db, number, trigger, config)
    api.deadline = time.monotonic()+1200  # Includes snapshot, model, tests and PR publication.
    run = RUNTIME / 'runs' / f'issue-{number}-attempt-{attempt}'
    checkout = run / 'checkout'
    checkout.mkdir(parents=True)
    audit('started', issue=number, attempt=attempt, trigger=trigger,
          task_sha256=hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest())
    def revoked():
        latest = api.api('GET', f'/issues/{number}')
        try:
            return actor_gate(latest, api.pages(f'/issues/{number}/events'), config['allowed_actors']) != trigger
        except Blocked:
            return True
    try:
        api.feedback(number, f'Task accepted: attempt {attempt}/2. Local isolated SAMPLE checkout; deadline 10 minutes for Codex. No deployment or merge.')
        base, tree = api.snapshot(checkout)
        audit('snapshot', issue=number, base=base, tree=tree)
        prepare(checkout)
        preflight(checkout, run)
        if not (RUNTIME / 'codex-home/auth.json').is_file():
            raise Blocked('Independent ChatGPT login required; run Automation Login.command locally')
        prompt = (ROOT / 'automation/task.md').read_text()+json.dumps(task, ensure_ascii=True)
        prompt_path = run / 'task.json'
        prompt_path.write_text(json.dumps(task, ensure_ascii=True))
        # Prompt is argv data, never interpolated into a shell command. No shell=True.
        env = clean_env(checkout / '.worker-tmp', checkout / '.worker-tmp')
        child(['codex', '-a', 'never', 'exec', '--ephemeral', '--ignore-rules', '--json',
               '-C', str(checkout), '-c', 'forced_login_method="chatgpt"', prompt], checkout,
               min(config['timeout_seconds'], max(1, int(api.deadline-time.monotonic()))), run / 'codex.jsonl', env, revoked)
        changes = diff(checkout, task['allowed_paths'])
        policy = json.loads((ROOT / 'automation/test_manifest.json').read_text())
        runner = (ROOT / 'automation/trusted_tests.py').read_text()
        child(sandbox(checkout, [sys.executable, '-c', runner, str(checkout), json.dumps(policy)]), checkout,
              min(config['test_timeout_seconds'], max(1, int(api.deadline-time.monotonic()))), run / 'tests.log', env, revoked)
        test_log = (run / 'tests.log').read_text(errors='replace')
        verify_test_result(test_log, policy)
        if diff(checkout, task['allowed_paths']) != changes:
            raise Blocked('Working files changed during tests; review before publication')
        if revoked() or stopped():
            raise Blocked('Authorization revoked before publication')
        url = api.publish(number, attempt, base, tree, changes)
        db.execute('UPDATE runs SET status=?,result=? WHERE id=?', ('pr', url, rowid));db.commit()
        audit('pr_created', issue=number, attempt=attempt, pr=url)
        api.feedback(number, f'Draft PR: {url}\nFixed unittest suite: PASS. Files: '+', '.join(x[0] for x in changes)+f'\nAttempt {attempt}/2. Manual acceptance required. Raw logs stay local; Goal/Acceptance must be reviewed in PR.')
    except Exception as exc:
        # Unknown errors are summarized by type; never publish arbitrary stderr/model output.
        reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        existing = db.execute('SELECT status FROM runs WHERE id=?', (rowid,)).fetchone()[0]
        if existing != 'pr':
            db.execute('UPDATE runs SET status=?,result=? WHERE id=?', ('blocked', reason, rowid));db.commit()
        audit('needs_attention', issue=number, attempt=attempt, reason=reason)
        api.deadline = None  # Permit bounded failure notification after task expiry.
        try:
            api.feedback(number, f'Needs attention: {reason}. Attempt {attempt}/2. No auto retry after this blocker; resolve it and remove/re-add codex-ready. PR may already exist if feedback failed; check PR list before retrying.')
        except Exception:
            audit('feedback_failed', issue=number, attempt=attempt)
        error = Blocked(reason)
        error.reported = True
        raise error from None
    finally:
        api.deadline = None


def once():
    config = settings()
    if not config['enabled'] or stopped():
        raise Blocked('Automation disabled or STOP active; no network/model calls made')
    env = clean_env(RUNTIME / 'codex-home', RUNTIME / 'codex-home')
    version = subprocess.check_output(['codex', '--version'], env=env, text=True, timeout=10).strip()
    if version != config['cli_version']:
        raise Blocked('CLI version changed; rerun isolation acceptance before enabling')
    token = (RUNTIME / 'github.token').read_text()
    if (RUNTIME / 'github.token').stat().st_mode & 0o077:
        raise Blocked('GitHub token file must have mode 0600')
    api = GitHub(token)
    repo = api.api('GET', '')
    if repo.get('full_name') != REPO or repo.get('private') is not False:
        raise Blocked('Only the exact authorized public repository is permitted')
    with (RUNTIME / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('One worker already running') from None
        with sqlite3.connect(RUNTIME / 'state.db') as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS notices(issue INTEGER,key TEXT,PRIMARY KEY(issue,key))')
            issues = api.pages('/issues?state=open&labels=codex-ready&sort=created&direction=asc')
            for issue in issues:
                if config['canary_issue'] is not None and issue['number'] != config['canary_issue']:
                    continue
                try:
                    run_issue(api, issue, config, db)
                    return
                except Blocked as exc:
                    audit('deferred', issue=issue['number'], reason=str(exc))
                    if (not getattr(exc, 'reported', False) and issue.get('user', {}).get('login') in config['allowed_actors']
                            and 'allowlisted' not in str(exc)):
                        key = hashlib.sha256(((issue.get('body') or '')+'\n'+str(exc)).encode()).hexdigest()
                        cursor = db.execute('INSERT OR IGNORE INTO notices VALUES(?,?)', (issue['number'], key))
                        db.commit()
                        if cursor.rowcount:
                            try:api.feedback(issue['number'], 'Task not started: '+str(exc)+'. Check structured scope, remaining attempts and authorization. No model invoked for this rejection.')
                            except Exception:audit('feedback_failed', issue=issue['number'])


def simulate():
    """Real git/diff/fixed suite, deterministic mock developer; no model or GitHub."""
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='cf-simulation-', dir=RUNTIME) as directory:
        run = Path(directory);checkout = run / 'checkout';checkout.mkdir()
        raw = subprocess.check_output(['/usr/bin/git', 'archive', 'HEAD'], cwd=ROOT, timeout=30)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(checkout, filter='data')
        prepare(checkout)
        task = parse_task({'number': 9000, 'title': 'SAMPLE simulation', 'body': '## Goal\nAdd a sample note.\n## Acceptance\nNote clearly says SAMPLE.\n## Allowed paths\n- docs/automation-demo.md\n## References\nREADME.md'}, [])
        (checkout / 'docs').mkdir(exist_ok=True)
        (checkout / 'docs/automation-demo.md').write_text('SAMPLE MODE — automation dry-run; no customer data.\n')
        changes = diff(checkout, task['allowed_paths'])
        child([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], checkout, 180,
              run / 'tests.log', clean_env(checkout / '.worker-tmp', checkout / '.worker-tmp'))
        tests = (run / 'tests.log').read_text()
        if not re.search(r'^OK\s*$', tests, re.M):
            raise Blocked('Simulation test suite did not pass')
        class FakeGitHub(GitHub):
            def __init__(self):self.calls=[]
            def api(self, method, route, data=None):
                self.calls.append((method, route, data))
                return {'sha': 'a'*40, 'html_url': 'https://example.invalid/SIMULATED-PR-NOT-CREATED'}
        api = FakeGitHub()
        url = api.publish(9000, 1, 'b'*40, 'c'*40, changes)
        api.feedback(9000, 'SIMULATED tests/PR feedback: '+url)
        report = {'mode': 'SIMULATION — NOT LIVE CODEX/GITHUB', 'patch': [x[0] for x in changes],
                  'api_operations_simulated': [x[:2] for x in api.calls], 'pr': url,
                  'fixed_suite': re.search(r'Ran (\d+) tests?', tests)[0]+'; OK (trusted base checkout)'}
        (RUNTIME / 'simulation.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


def main():
    def terminate(signum, frame):
        raise KeyboardInterrupt('Worker interrupted; stopping active process group')
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'doctor', 'once', 'watch', 'stop', 'simulate'])
    command = parser.parse_args().command
    if command == 'init':
        initialize();print('Initialized, disabled. No login copied or service installed.');return
    if command == 'stop':
        RUNTIME.mkdir(exist_ok=True);(RUNTIME / 'STOP').touch();print('STOP set; active child stops within polling interval.');return
    if command == 'simulate':
        simulate();return
    if command == 'doctor':
        config = settings()
        print(json.dumps({'enabled': config['enabled'], 'stop': stopped(), 'codex': shutil.which('codex'),
            'canary_issue_only': config['canary_issue'],
            'project_chatgpt_login_present': (RUNTIME / 'codex-home/auth.json').is_file(),
            'project_github_token_present': (RUNTIME / 'github.token').is_file(),
            'warning': 'presence is not authentication or isolation verification'}, indent=2));return
    if command == 'once':
        once();return
    while not stopped():
        try:once()
        except Exception as exc:audit('poll_failed', reason=str(exc) if isinstance(exc, Blocked) else type(exc).__name__)
        # Foreground only, interruptible, Mac must be awake; no launchd installation.
        for _ in range(settings()['poll_seconds']):
            if stopped():return
            time.sleep(1)


if __name__ == '__main__':
    try:main()
    except (Blocked, FileNotFoundError) as exc:
        print('BLOCKED: '+(str(exc) if isinstance(exc, Blocked) else 'Initialize project settings/credentials first. No credentials printed.'), file=sys.stderr)
        sys.exit(2)
