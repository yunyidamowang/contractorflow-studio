"""POSIX task deadline and stop monitoring; no model or credential handling."""
import os
from pathlib import Path
import signal
import threading
import time


class TaskStopped(RuntimeError):
    pass


def local_stop(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _terminate_group(process, grace=3):
    # The leader may exit while descendants remain in its process group.
    try:os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:return
    end=time.monotonic()+grace
    while time.monotonic()<end:
        process.poll()  # Reap the leader before probing the group.
        try:os.killpg(process.pid, 0)
        except ProcessLookupError:return
        time.sleep(.05)
    try:os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:pass
    process.wait(timeout=1)


def terminate_group(process, grace=3):
    # Defer timer interruption until group cleanup has finished (at most grace+1s).
    mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
    try:_terminate_group(process,grace)
    finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)


class TaskGuard:
    """OS interval timer interrupts blocking supervisor I/O; remote I/O is separate.

    SIGALRM is reserved by this single-threaded dispatcher. Child process groups
    are always cleaned by their finally blocks. Not a kernel/VM isolation limit.
    """
    def __init__(self, seconds, stop_path, remote_stop, clock=time.monotonic):
        if type(seconds) is not int or not 30 <= seconds <= 1200:
            raise ValueError('total_timeout_seconds must be 30..1200')
        self.clock=clock;self.deadline=clock()+seconds
        self.stop_path=Path(stop_path);self.remote_stop=remote_stop
        self.remote_checked=clock();self.remote_failed=False
        self.done=threading.Event();self.reason=None

    def check(self):
        if self.reason:raise TaskStopped(self.reason)
        if self.clock()>=self.deadline:self.reason='task_timeout'
        elif local_stop(self.stop_path):self.reason='local_stop'
        elif self.remote_failed or self.clock()-self.remote_checked>25:self.reason='remote_stop_or_unavailable'
        if self.reason:raise TaskStopped(self.reason)

    def poll_remote(self):
        while not self.done.wait(2):
            try:failed=bool(self.remote_stop())
            except Exception:failed=True
            self.remote_failed=self.remote_failed or failed
            self.remote_checked=self.clock()
            if failed:return

    def alarm(self, *_):
        try:self.check()
        except TaskStopped:
            signal.setitimer(signal.ITIMER_REAL, 0)
            raise

    def __enter__(self):
        if threading.current_thread() is not threading.main_thread() or signal.getitimer(signal.ITIMER_REAL)[0]:
            raise TaskStopped('watchdog_unavailable')
        self.check()
        self.previous=signal.signal(signal.SIGALRM,self.alarm)
        self.thread=threading.Thread(target=self.poll_remote,daemon=True)
        self.thread.start()
        signal.setitimer(signal.ITIMER_REAL,.1,.1)
        return self

    def __exit__(self,*_):
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,self.previous)
        self.done.set()
