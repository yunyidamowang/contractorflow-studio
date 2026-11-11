import signal
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from automation.task_guard import TaskGuard, TaskStopped, local_stop, terminate_group
from automation.dispatcher import GitHub


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
        from automation.dispatcher import run_issue, Blocked
        api=Mock()
        event={'id':9,'event':'labeled','label':{'name':'codex-ready'},'actor':{'login':'owner'}}
        api.pages.side_effect=lambda route: [event] if route.endswith('/events') else ([{'number':99}] if 'codex-stop' in route else [])
        api.api.return_value=issue()
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
