#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One node agent per data folder. Python 3.8+ standard library only.

Why: agent 2.11 registers a Startup shortcut for START.bat by itself, and the owner may still double-click START.bat. Two agents
with the same token and the same data folder would run two GPU jobs on a one-slot node, pip-install into the same venvs twice,
flush the same outbox and start the same services against each other.

How: an exclusive OS lock on one byte of <data>\agent.lock for the whole life of the process (msvcrt.locking on Windows, flock
elsewhere). The OS drops it when the process dies - however it dies - so there is never a stale lock to clean up. The second
START.bat window does NOT exit (START.bat would restart it every 10 s and update.py would count each exit against a fresh update
and roll it back): it waits as a hot standby, says so once a minute, and takes over the moment the first agent stops.

    lock = InstanceLock(path)
    if lock.acquire(): ...we are the agent...        (keep `lock` referenced until the process ends)
    else: lock.holder()  -> {"pid": ..., "since": ..., "started": ...}
"""
import json
import os
import sys
import time

IS_WIN = sys.platform.startswith("win")
INFO_AT = 1                     # byte 0 is the locked byte; the human-readable info starts after it (a locked byte cannot be read)


def _lock_fd(fd):
    """Take the lock on byte 0 without waiting; True/False."""
    if IS_WIN:
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_fd(fd):
    try:
        if IS_WIN:
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


class InstanceLock:
    def __init__(self, path, backend=None):
        self.path = path
        self.fd = None
        self._lock = backend[0] if backend else _lock_fd          # (lock, unlock) can be replaced in tests
        self._unlock = backend[1] if backend else _unlock_fd

    def acquire(self):
        """True when this process now holds the lock (calling it again is fine); False when another process does."""
        if self.fd is not None:
            return True
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            got = self._lock(fd)                                  # (Windows may lock a byte beyond the end of a fresh file)
        except OSError:
            os.close(fd)
            raise
        if not got:
            os.close(fd)
            return False
        self.fd = fd
        self._write_info()
        return True

    def _write_info(self):
        info = {"pid": os.getpid(), "since": time.time(), "started": time.strftime("%Y-%m-%d %H:%M:%S"), "exe": sys.executable}
        try:
            os.lseek(self.fd, INFO_AT, os.SEEK_SET)
            data = json.dumps(info).encode("utf-8")
            os.write(self.fd, data)
            try:
                os.ftruncate(self.fd, INFO_AT + len(data))        # an older, longer note must not stay behind
            except (OSError, AttributeError):
                pass
        except OSError:
            pass                                                 # the lock is what matters, not the note

    def holder(self):
        """What the running agent wrote about itself ({} when unknown)."""
        try:
            with open(self.path, "rb") as fh:
                fh.seek(INFO_AT)
                return json.loads(fh.read(4096).decode("utf-8") or "{}")
        except (OSError, ValueError):
            return {}

    def release(self):
        if self.fd is None:
            return
        self._unlock(self.fd)
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None


def wait_for_turn(lock, say=print, poll_s=5.0, say_every_s=60.0, sleep=time.sleep, clock=time.time, stop=lambda: False):
    """Block until `lock` is ours (a standby window waiting for the running agent to stop). `say(text)` is called now and then so the
    window explains itself. Returns True when the lock was taken, False when stop() said to give up."""
    if lock.acquire():
        return True
    h = lock.holder()
    say("another processing-node agent is already running on this data folder (process %s, since %s). This window waits as a "
        "standby and takes over when that one stops - you can close this window." % (h.get("pid") or "?", h.get("started") or "?"))
    last = clock()
    while not stop():
        sleep(poll_s)
        if lock.acquire():
            say("the other agent stopped - this window is the node now.")
            return True
        if clock() - last >= say_every_s:
            last = clock()
            say("still waiting: the agent in the other window (process %s) is running." % (lock.holder().get("pid") or "?"))
    return False
