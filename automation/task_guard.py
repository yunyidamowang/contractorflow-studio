"""POSIX task deadline and stop monitoring; no model or credential handling."""
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
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
        except PermissionError:pass  # Probe denied: still escalate after the bounded grace.
        time.sleep(.05)
    try:os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:pass
    process.wait(timeout=1)


def terminate_group(process, grace=3):
    # Defer timer interruption until group cleanup has finished (at most grace+1s).
    mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
    try:_terminate_group(process,grace)
    finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)


_BOOTSTRAP = """import os, sys
os.chdir(sys.argv[1])
try:
    names = os.listdir('/dev/fd')
except OSError:
    names = []
for name in names:
    try:
        fd = int(name)
    except ValueError:
        continue
    if fd > 2:
        try:
            os.close(fd)
        except OSError:
            pass
try:
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
except OSError:
    raise SystemExit(127)
"""


class SessionProcess:
    """A session leader started with posix_spawn. poll/wait/communicate match the calls we use."""

    def __init__(self, pid, stdout, args):
        self.pid = pid
        self.args = args
        self.returncode = None
        self._stdout = stdout

    def close_stdout(self):
        if self._stdout is not None:
            try:
                os.close(self._stdout)
            except OSError:
                pass
            self._stdout = None

    def poll(self):
        if self.returncode is None:
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
            except InterruptedError:
                return None
            except ChildProcessError:
                self.returncode = -1
                return self.returncode
            if pid == 0:
                return None
            self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is not None:
            return self.returncode
        end = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if end is not None and time.monotonic() >= end:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.02)
        return self.returncode

    def communicate(self, timeout=None):
        chunks = []
        end = None if timeout is None else time.monotonic() + timeout
        if self._stdout is not None:
            while True:
                remaining = None if end is None else end - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise subprocess.TimeoutExpired(self.args, timeout, output=b''.join(chunks))
                try:
                    ready, _, _ = select.select([self._stdout], [], [], 0.05 if remaining is None else min(0.05, max(remaining, 0)))
                except InterruptedError:
                    continue
                if not ready:
                    continue
                try:
                    chunk = os.read(self._stdout, 65536)
                except InterruptedError:
                    continue
                if not chunk:
                    break
                chunks.append(chunk)
            self.close_stdout()
        self.wait(None if end is None else max(0, end - time.monotonic()))
        return b''.join(chunks), None


def _resolve(program, env):
    if os.path.dirname(program):
        if not os.access(program, os.X_OK):
            raise FileNotFoundError(program)
        return program
    found = shutil.which(program, path=env.get('PATH'))
    if not found:
        raise FileNotFoundError(program)
    return found


def _spawn(args, cwd, env, stdout, stderr, child_mask):
    program = _resolve(args[0], env)
    argv = [program, *list(args[1:])]
    read_fd = write_fd = None
    actions = [(os.POSIX_SPAWN_OPEN, 0, '/dev/null', os.O_RDONLY, 0)]
    try:
        if stdout == 'pipe':
            read_fd, write_fd = os.pipe()
            if read_fd <= 2 or write_fd <= 2:
                raise OSError('stdio pipe collided with standard descriptors')
            actions += [
                (os.POSIX_SPAWN_DUP2, write_fd, 1),
                (os.POSIX_SPAWN_CLOSE, read_fd),
                (os.POSIX_SPAWN_CLOSE, write_fd),
            ]
        else:
            actions.append((os.POSIX_SPAWN_DUP2, int(stdout), 1))
        if stderr == 'stdout':
            actions.append((os.POSIX_SPAWN_DUP2, 1, 2))
        elif stderr == 'devnull':
            actions.append((os.POSIX_SPAWN_OPEN, 2, '/dev/null', os.O_WRONLY, 0))
        else:
            raise ValueError('unsupported stderr mode')
        pid = os.posix_spawn(
            sys.executable,
            [sys.executable, '-c', _BOOTSTRAP, os.fspath(cwd), *argv],
            {str(key): str(value) for key, value in env.items()},
            file_actions=actions, setsid=True, setsigmask=[int(item) for item in child_mask])
    except BaseException:
        for fd in (read_fd, write_fd):
            if fd is not None:
                os.close(fd)
        raise
    if write_fd is not None:
        os.close(write_fd)
    return SessionProcess(pid, read_fd, argv)


def call_session(args, fn, *, cwd, env, stdout, stderr):
    """Run args in a new session and always terminate that process group.

    SIGALRM is blocked before posix_spawn and stays blocked until this frame
    holds the pid. The child receives the mask from before that block.
    """
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
    process = None
    try:
        process = _spawn(args, cwd, env, stdout, stderr, previous)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        return fn(process)
    finally:
        try:
            if process is not None:
                process.close_stdout()
                terminate_group(process)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)


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
