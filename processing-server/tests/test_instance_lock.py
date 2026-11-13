"""One agent per data folder. The second START.bat window must not become a second agent (two GPU jobs on a one-slot node,
two installers in the same venvs ...) and must not exit either (START.bat would restart it every 10 s and update.py would count the exits
against a fresh update); it waits as a standby and takes over when the first agent stops."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import instance_lock as il  # noqa: E402


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-lock-test-")
        self.path = os.path.join(self.tmp, "sub", "agent.lock")
        self.locks = []

    def tearDown(self):
        for lk in self.locks:
            lk.release()

    def mk(self, **kw):
        lk = il.InstanceLock(self.path, **kw)
        self.locks.append(lk)
        return lk

    def test_the_second_holder_is_refused_until_the_first_lets_go(self):
        a, b = self.mk(), self.mk()
        self.assertTrue(a.acquire())
        self.assertTrue(a.acquire())                              # asking again is fine
        self.assertFalse(b.acquire())
        self.assertIsNone(b.fd)
        a.release()
        self.assertTrue(b.acquire())
        self.assertFalse(a.acquire())

    def test_the_holder_note_names_the_running_agent(self):
        a, b = self.mk(), self.mk()
        a.acquire()
        info = b.holder()
        self.assertEqual(info["pid"], os.getpid())
        self.assertIn("started", info)
        a.release()
        b.acquire()
        raw = open(self.path, "rb").read()
        self.assertEqual(json.loads(raw[il.INFO_AT:].decode("utf-8"))["pid"], os.getpid())       # one clean note, no leftovers of an older one

    def test_a_process_that_dies_frees_the_lock(self):
        code = ("import sys, time; sys.path.insert(0, %r); import instance_lock as il; lk = il.InstanceLock(%r); "
                "print('held' if lk.acquire() else 'refused', flush=True); time.sleep(120)" % (HERE, self.path))
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "held")
            mine = self.mk()
            self.assertFalse(mine.acquire())                      # another PROCESS holds it
            self.assertEqual(mine.holder()["pid"], p.pid)
        finally:
            p.kill()
            p.wait()
        mine = self.mk()
        deadline = time.time() + 10
        while time.time() < deadline and not mine.acquire():
            time.sleep(0.2)
        self.assertIsNotNone(mine.fd)                             # killed, not released politely: the OS dropped the lock

    def test_a_standby_window_waits_and_takes_over(self):
        a, b = self.mk(), self.mk()
        a.acquire()
        said, polls = [], []

        def sleep(s):
            polls.append(s)
            if len(polls) == 3:
                a.release()                                       # the running agent stops

        self.assertTrue(il.wait_for_turn(b, say=said.append, poll_s=5, sleep=sleep, clock=lambda: len(polls) * 5.0))
        self.assertEqual(len(polls), 3)
        self.assertIn("already running", said[0])
        self.assertIn(str(os.getpid()), said[0])
        self.assertIn("takes over", said[0])
        self.assertIn("this window is the node now", said[-1])

    def test_a_standby_window_reminds_once_a_minute_and_can_be_stopped(self):
        a, b = self.mk(), self.mk()
        a.acquire()
        said, ticks = [], []
        clock = {"t": 0.0}

        def sleep(s):
            clock["t"] += 30
            ticks.append(s)

        self.assertFalse(il.wait_for_turn(b, say=said.append, poll_s=5, say_every_s=60, sleep=sleep, clock=lambda: clock["t"],
                                          stop=lambda: len(ticks) >= 6))
        self.assertEqual(len(said), 1 + 3)                        # the first notice + a reminder every 60 s of the 180 s waited
        self.assertTrue(all("still waiting" in s for s in said[1:]))


class WindowsBackendTests(unittest.TestCase):
    """msvcrt.locking: one byte at offset 0, never waiting (LK_NBLCK); a refusal is an OSError."""

    def setUp(self):
        self.calls = []
        self.busy = False
        fake = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0)

        def locking(fd, mode, n):
            self.calls.append((mode, n, os.lseek(fd, 0, os.SEEK_CUR)))
            if self.busy and mode == fake.LK_NBLCK:
                raise PermissionError(13, "locked")

        fake.locking = locking
        self.fake = fake

    def test_lock_and_unlock_use_the_first_byte(self):
        tmp = tempfile.mkdtemp(prefix="nm-lock-win-")
        with mock.patch.object(il, "IS_WIN", True), mock.patch.dict(sys.modules, {"msvcrt": self.fake}):
            lk = il.InstanceLock(os.path.join(tmp, "agent.lock"))
            self.assertTrue(lk.acquire())
            self.assertEqual(self.calls[0], (2, 1, 0))            # LK_NBLCK, 1 byte, at offset 0
            lk.release()
            self.assertEqual(self.calls[-1], (0, 1, 0))           # LK_UNLCK of the same byte
            self.busy = True
            other = il.InstanceLock(os.path.join(tmp, "agent.lock"))
            self.assertFalse(other.acquire())                     # the OS says it is locked
            self.assertIsNone(other.fd)


class AgentHookTests(unittest.TestCase):
    def setUp(self):
        import agent

        self.agent = agent
        self.tmp = tempfile.mkdtemp(prefix="nm-lock-agent-")
        self.patch = mock.patch.object(agent, "DATA", self.tmp)
        self.patch.start()
        self.logs = []
        self.log_patch = mock.patch.object(agent, "log", side_effect=lambda m, level="INFO": self.logs.append(m))
        self.log_patch.start()
        agent.INSTANCE_LOCK = None

    def tearDown(self):
        if self.agent.INSTANCE_LOCK is not None:
            self.agent.INSTANCE_LOCK.release()
        self.agent.INSTANCE_LOCK = None
        self.log_patch.stop()
        self.patch.stop()

    def test_the_agent_takes_the_lock_and_a_second_one_cannot(self):
        self.agent.take_instance_lock()
        self.assertIsNotNone(self.agent.INSTANCE_LOCK)
        self.assertIsNotNone(self.agent.INSTANCE_LOCK.fd)
        other = il.InstanceLock(os.path.join(self.tmp, "agent.lock"))
        self.assertFalse(other.acquire())
        self.assertEqual(other.holder()["pid"], os.getpid())

    def test_a_second_agent_is_a_standby_that_says_so_and_takes_over(self):
        first = il.InstanceLock(os.path.join(self.tmp, "agent.lock"))
        self.assertTrue(first.acquire())
        n = {"polls": 0}

        def sleep(s):
            n["polls"] += 1
            if n["polls"] == 2:
                first.release()

        real_wait = il.wait_for_turn

        def quick_wait(lock, **kw):                               # the agent calls wait_for_turn with its normal 5 s poll: skip the real waiting
            return real_wait(lock, sleep=sleep, **kw)

        with mock.patch.object(il, "wait_for_turn", quick_wait):
            self.agent.take_instance_lock()
        self.assertEqual(n["polls"], 2)
        self.assertTrue(any("already running" in m for m in self.logs))
        self.assertIsNotNone(self.agent.INSTANCE_LOCK.fd)

    def test_a_broken_guard_never_keeps_the_node_down(self):
        class Boom:
            def InstanceLock(self, path):
                raise PermissionError(13, "no permission on the data folder")

        with mock.patch.object(self.agent, "instance_lock_mod", Boom()), mock.patch.object(self.agent, "warn") as warn:
            self.agent.take_instance_lock()                       # must not raise
        self.assertIsNone(self.agent.INSTANCE_LOCK)
        self.assertTrue(warn.called)

    def test_the_escape_hatch(self):
        with mock.patch.dict(os.environ, {"NM_ALLOW_SECOND_AGENT": "1"}):
            self.agent.take_instance_lock()
        self.assertIsNone(self.agent.INSTANCE_LOCK)

    def test_the_module_is_part_of_the_code_stamp_and_main_takes_the_lock_before_the_work_folder(self):
        self.assertIn("instance_lock.py", self.agent.CODE_FILES)
        src = open(os.path.join(HERE, "agent.py"), encoding="utf-8").read()
        main = src[src.index("\ndef main():"):]
        self.assertLess(main.index("take_instance_lock()"), main.index("os.makedirs(WORK"))
        self.assertLess(main.index('"--prepare" in sys.argv'), main.index("take_instance_lock()"))     # START.bat's --prepare / --version never wait


if __name__ == "__main__":
    unittest.main()
