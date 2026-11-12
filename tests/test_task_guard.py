import os
import signal
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from automation.task_guard import TaskGuard, TaskStopped, call_session, local_stop, terminate_group
from automation.dispatcher import Blocked, GitHub


class GuardTests(unittest.TestCase):
    def guard(self, root, clock):return TaskGuard(30,Path(root)/'STOP',lambda:False,clock)

    def test_deadline_and_stop_checks(self):
        with tempfile.TemporaryDirectory() as root:
            now=[0];g=self.guard(root,lambda:now[0]);g.check()
            now[0]=30
            with self.assertRaisesRegex(TaskStopped,'timeout'):g.check()
            g=self.guard(root,lambda:now[0]);(Path(root)/'STOP').touch()
            with self.assertRaisesRegex(TaskStopped,'local_stop'):g.check()

    def test_unreadable_stop_fails_closed(self):
        with patch.object(Path,'lstat',side_effect=PermissionError):self.assertTrue(local_stop(Path('synthetic')))

    def test_remote_failure_and_stale_state(self):
        with tempfile.TemporaryDirectory() as root:
            for failure in ('error','label','stale'):
                now=[0];g=self.guard(root,lambda:now[0])
                if failure=='stale':now[0]=26
                else:
                    g.remote_stop=Mock(side_effect=OSError) if failure=='error' else lambda:True
                    g.done=Mock();g.done.wait.return_value=False;g.poll_remote()
                with self.assertRaisesRegex(TaskStopped,'remote_stop'):g.check()

    def test_timer_interrupts_blocking_supervisor(self):
        with tempfile.TemporaryDirectory() as root:
            g=self.guard(root,time.monotonic);g.deadline=time.monotonic()+.15
            started=time.monotonic()
            with self.assertRaises(TaskStopped):
                with g:time.sleep(3)
            self.assertLess(time.monotonic()-started,1)
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_running_stop_timer(self):
        with tempfile.TemporaryDirectory() as root:
            g=self.guard(root,time.monotonic)
            with self.assertRaisesRegex(TaskStopped,'local_stop'):
                with g:
                    (Path(root)/'STOP').touch();time.sleep(3)

    def test_dead_leader_descendants_receive_kill(self):
        process=Mock(pid=123);process.poll.return_value=0
        with patch('automation.task_guard.os.killpg') as kill, patch('automation.task_guard.time.monotonic',side_effect=[0,0,4]), patch('automation.task_guard.time.sleep'):
            terminate_group(process)
        self.assertIn(((123,signal.SIGTERM),),kill.call_args_list)
        self.assertIn(((123,signal.SIGKILL),),kill.call_args_list)

    def test_remote_stop_blocks_post_before_network(self):
        with tempfile.TemporaryDirectory() as root:
            api=GitHub('SYNTHETIC');g=self.guard(root,time.monotonic);api.guard=g
            for probe in (lambda:True,Mock(side_effect=OSError)):
                g.remote_stop=probe
                with patch('automation.dispatcher.urllib.request.build_opener') as network:
                    with self.assertRaises(TaskStopped):api.api('POST','/issues/4/comments',{'body':'synthetic'})
                    network.assert_not_called()

    def test_configuration_bounds(self):
        for value in (0,29,1201,True,'30'):
            with self.assertRaises(ValueError):TaskGuard(value,Path('STOP'),lambda:False)

    def test_timeout_is_recorded_and_cannot_repeat(self):
        from test_automation import AutomationTest
        with patch.object(TaskGuard,'__enter__',side_effect=TaskStopped('task_timeout')):
            AutomationTest('test_simulated_issue_model_tests_pr_feedback').pipeline(test_exit=True)

    def test_global_label_rejects_before_reservation(self):
        from test_automation import issue
        from automation.dispatcher import run_issue
        api=Mock()
        event={'id':9,'event':'labeled','label':{'name':'codex-ready'},'actor':{'login':'owner'}}
        api.pages.side_effect=lambda route: [event] if route.endswith('/events') else ([{'number':99}] if 'codex-stop' in route else [])
        api.api.side_effect=lambda method, route, data=None: {'name': 'codex-stop'} if route == '/labels/codex-stop' else issue()
        with patch('automation.dispatcher.stopped',return_value=False), patch('automation.dispatcher.reserve') as reserve:
            with self.assertRaises(Blocked):run_issue(api,issue(),{'allowed_actors':['owner']},Mock())
            reserve.assert_not_called()

    def test_denied_probe_still_escalates(self):
        process=Mock(pid=123)
        def probe(pid,sig):
            if sig==0:raise PermissionError()
        with patch('automation.task_guard.os.killpg',side_effect=probe) as kill, patch('automation.task_guard.time.monotonic',side_effect=[0,0,4]), patch('automation.task_guard.time.sleep'):
            terminate_group(process)
        self.assertIn(((123,signal.SIGKILL),),kill.call_args_list)

    def _restore_alarm(self, saved_mask, saved_handler):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, saved_handler)
        signal.pthread_sigmask(signal.SIG_SETMASK, saved_mask)

    def test_alarm_during_spawn_reaps_process_group(self):
        spawned = []
        real = os.posix_spawn
        def wrapped(*args, **kwargs):
            pid = real(*args, **kwargs)
            spawned.append(pid)
            os.kill(os.getpid(), signal.SIGALRM)
            return pid
        def handler(signum, frame):
            raise TaskStopped('task_timeout')
        saved_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        saved_handler = signal.signal(signal.SIGALRM, handler)
        try:
            with tempfile.TemporaryDirectory() as root:
                env = {'PATH': os.environ['PATH'], 'HOME': root, 'TMPDIR': root, 'LANG': 'C'}
                with patch('automation.task_guard.os.posix_spawn', wrapped):
                    with self.assertRaises(TaskStopped):
                        call_session([sys.executable, '-c', 'import time; time.sleep(30)'], lambda process: None,
                            cwd=root, env=env, stdout='pipe', stderr='devnull')
            self.assertTrue(spawned)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(spawned[0], 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail('process group leaked after alarm during spawn')
        finally:
            self._restore_alarm(saved_mask, saved_handler)
            for pid in spawned:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_exited_leader_kill_reaps_ignoring_grandchild(self):
        script = (
            'import os,signal,sys,time\n'
            'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            'if os.fork()==0:\n'
            '    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            '    blocked=signal.SIGALRM in signal.pthread_sigmask(signal.SIG_BLOCK, set())\n'
            '    open(sys.argv[1],"w").write("%s %d"%(os.getpid(), int(blocked)))\n'
            '    time.sleep(30)\n'
            '    os._exit(0)\n'
            'os._exit(0)\n'
        )
        with tempfile.TemporaryDirectory() as root:
            pidfile = str(Path(root)/'grand.pid')
            env = {'PATH': os.environ['PATH'], 'HOME': root, 'TMPDIR': root, 'LANG': 'C'}
            leader = []
            def body(process):
                leader.append(process.pid)
                deadline = time.monotonic()+2
                while time.monotonic() < deadline and not os.path.exists(pidfile):
                    time.sleep(0.01)
                self.assertTrue(os.path.exists(pidfile), 'grandchild pid file missing')
                process.wait(timeout=2)
                gpid_text, blocked = Path(pidfile).read_text().split()
                self.assertEqual(blocked, '0')
                gpid = int(gpid_text)
                terminate_group(process, grace=0.2)
                deadline = time.monotonic()+2
                while time.monotonic() < deadline:
                    try:
                        os.kill(gpid, 0)
                    except ProcessLookupError:
                        return
                    time.sleep(0.02)
                self.fail('grandchild survived KILL')
            call_session([sys.executable, '-c', script, pidfile], body,
                cwd=root, env=env, stdout='pipe', stderr='devnull')
            for pid in leader:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def _stop_api(self, label=None, pages_error=None, label_error=None):
        from test_automation import issue
        api = Mock()
        event = {'id': 9, 'event': 'labeled', 'label': {'name': 'codex-ready'}, 'actor': {'login': 'owner'}}
        def pages(route):
            if pages_error and 'codex-stop' in route:
                raise pages_error
            if route.endswith('/events'):
                return [event]
            if 'codex-stop' in route:
                return [{'number': 99}] if label == 'present-and-used' else []
            return []
        def api_call(method, route, data=None):
            if route == '/labels/codex-stop':
                if label_error:
                    raise label_error
                if label == 'missing':
                    raise Blocked('GitHub http failure HTTP 404')
                return {'name': 'codex-stop'}
            return issue()
        api.pages.side_effect = pages
        api.api.side_effect = api_call
        return api

    def _assert_stop_before_reserve(self, api):
        from test_automation import issue
        from automation.dispatcher import run_issue
        with patch('automation.dispatcher.stopped', return_value=False), patch('automation.dispatcher.reserve') as reserve:
            with self.assertRaisesRegex(Blocked, 'Global STOP'):
                run_issue(api, issue(), {'allowed_actors': ['owner']}, Mock())
            reserve.assert_not_called()

    def test_missing_stop_label_is_stop(self):
        self._assert_stop_before_reserve(self._stop_api(label='missing'))

    def test_stop_label_lookup_error_is_stop(self):
        self._assert_stop_before_reserve(self._stop_api(label_error=OSError('synthetic lookup failure')))
        self._assert_stop_before_reserve(self._stop_api(pages_error=OSError('synthetic pages failure')))

    def test_clear_stop_label_allows_reservation(self):
        from test_automation import issue
        from automation.dispatcher import run_issue
        api = self._stop_api(label='clear')
        with patch('automation.dispatcher.stopped', return_value=False), patch('automation.dispatcher.reserve', side_effect=Blocked('reserved-sentinel')) as reserve:
            with self.assertRaisesRegex(Blocked, 'reserved-sentinel'):
                run_issue(api, issue(), {'allowed_actors': ['owner']}, Mock())
            reserve.assert_called_once()

    def test_stop_label_route_is_exact(self):
        from automation.dispatcher import Blocked
        api = GitHub('synthetic-not-a-token')
        with patch('automation.dispatcher.urllib.request.build_opener') as network:
            for route in ('/labels/codex-ready', '/labels/codex-stop/extra', '/labels'):
                with self.assertRaises(Blocked):
                    api.api('GET', route)
            network.assert_not_called()

    def _run_once(self, exc, stop_pages=False):
        from automation.dispatcher import once, Blocked, REPO
        feedbacks = []
        writes = []
        class FakeAPI:
            def __init__(self, token):
                pass
            def api(self, method, route, data=None):
                if method != 'GET' or data is not None:
                    writes.append((method, route))
                if route == '/labels/codex-stop':
                    return {'name': 'codex-stop'}
                return {'full_name': REPO, 'private': False}
            def pages(self, route):
                if 'codex-stop' in route:
                    return [{'number': 9}] if stop_pages else []
                if 'codex-ready' in route:
                    return [{'number': 4, 'user': {'login': 'owner'}, 'body': 'synthetic body', 'state': 'open'}]
                return []
            def feedback(self, number, message):
                feedbacks.append((number, message))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            token = root/'github.token'
            token.write_text('SYNTHETIC TOKEN')
            token.chmod(0o600)
            config = {'enabled': True, 'cli_version': 'codex-cli 0.144.6', 'canary_issue': 4, 'allowed_actors': ['owner']}
            side = exc
            with patch('automation.dispatcher.RUNTIME', root), patch('automation.dispatcher.settings', return_value=config), \
                    patch('automation.dispatcher.subprocess.check_output', return_value='codex-cli 0.144.6'), \
                    patch('automation.dispatcher.GitHub', FakeAPI), \
                    patch('automation.dispatcher.global_stop', return_value=False), \
                    patch('automation.dispatcher.run_issue', side_effect=side):
                once()
        return feedbacks, writes

    def test_global_stop_does_not_comment(self):
        from automation.dispatcher import Blocked
        feedbacks, writes = self._run_once(Blocked('Global STOP active'))
        self.assertEqual(feedbacks, [])
        self.assertEqual(writes, [])
        from automation.dispatcher import once, REPO
        feedbacks = []
        class FakeAPI:
            def __init__(self, token):
                pass
            def api(self, method, route, data=None):
                if method != 'GET' or data is not None:
                    raise AssertionError('github write during global stop')
                if route == '/labels/codex-stop':
                    return {'name': 'codex-stop'}
                return {'full_name': REPO, 'private': False}
            def pages(self, route):
                if 'codex-stop' in route:
                    return [{'number': 9}]
                return [{'number': 4, 'user': {'login': 'owner'}, 'body': 'synthetic'}]
            def feedback(self, number, message):
                feedbacks.append(message)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            token = root/'github.token'
            token.write_text('SYNTHETIC TOKEN')
            token.chmod(0o600)
            config = {'enabled': True, 'cli_version': 'codex-cli 0.144.6', 'canary_issue': 4, 'allowed_actors': ['owner']}
            with patch('automation.dispatcher.RUNTIME', root), patch('automation.dispatcher.settings', return_value=config), \
                    patch('automation.dispatcher.subprocess.check_output', return_value='codex-cli 0.144.6'), \
                    patch('automation.dispatcher.GitHub', FakeAPI):
                once()
        self.assertEqual(feedbacks, [])

    def test_other_rejection_still_comments(self):
        from automation.dispatcher import Blocked
        feedbacks, writes = self._run_once(Blocked('Missing structured section: Goal'))
        self.assertEqual(writes, [])
        self.assertEqual(len(feedbacks), 1)
        self.assertIn('Task not started', feedbacks[0][1])
        self.assertNotIn('Global STOP', feedbacks[0][1])

    def test_publication_record_survives_alarm(self):
        from automation.dispatcher import note_publication, reserve
        recorded = []
        def handler(signum, frame):
            raise TaskStopped('task_timeout')
        saved_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        saved_handler = signal.signal(signal.SIGALRM, handler)
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with sqlite3.connect(root/'state.db') as db, patch('automation.dispatcher.RUNTIME', root):
                    db.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,issue INTEGER,trigger TEXT,status TEXT,started REAL,day TEXT,result TEXT)')
                    rowid = db.execute('INSERT INTO runs(issue,trigger,status,started,day) VALUES(?,?,?,?,?)', (4, 'trig', 'running', time.time(), '2026-11-11')).lastrowid
                    db.commit()
                    api = GitHub('synthetic-not-a-token')
                    pulls = []
                    def fake_api(method, route, data=None):
                        if route == '/pulls':
                            pulls.append(route)
                            os.kill(os.getpid(), signal.SIGALRM)
                            return {'html_url': 'https://example.invalid/SIMULATED-PR'}
                        return {'sha': 'a'*40}
                    api.api = fake_api
                    def record(url):
                        note_publication(db, rowid, 4, 1, url)
                        recorded.append(url)
                        self.assertIn(signal.SIGALRM, signal.pthread_sigmask(signal.SIG_BLOCK, set()))
                    with self.assertRaises(TaskStopped):
                        api.publish(4, 1, 'b'*40, 'c'*40, [('docs/sample.md', b'SAMPLE\n', '100644')], record=record)
                    status, result = db.execute('SELECT status,result FROM runs WHERE id=?', (rowid,)).fetchone()
                    self.assertEqual(status, 'pr')
                    self.assertEqual(result, 'https://example.invalid/SIMULATED-PR')
                    self.assertEqual(recorded, ['https://example.invalid/SIMULATED-PR'])
                    self.assertEqual(pulls, ['/pulls'])
                    lines = (root/'audit.jsonl').read_text().splitlines()
                    self.assertTrue(lines)
                    import json
                    parsed = [json.loads(line) for line in lines]
                    self.assertEqual([row['event'] for row in parsed], ['pr_created'])
                    self.assertEqual(parsed[0]['pr'], 'https://example.invalid/SIMULATED-PR')
                    with self.assertRaises(Blocked):
                        reserve(db, 4, 'trig', {'max_attempts_per_issue': 2, 'max_runs_per_day': 3, 'retry_delay_seconds': 0})
                    self.assertEqual(pulls, ['/pulls'])
        finally:
            self._restore_alarm(saved_mask, saved_handler)

    def test_recorded_pr_is_not_downgraded_or_repeated(self):
        from test_automation import AutomationTest
        def boom():
            raise TaskStopped('task_timeout')
        AutomationTest('test_simulated_issue_model_tests_pr_feedback').pipeline(after_record=boom)
