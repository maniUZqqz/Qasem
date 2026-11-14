# -*- coding: utf-8 -*-
"""«صبحِ مالک» با عاملِ واقعی — آزمونِ سرتاسریِ اختیاری (۱۴۰۵/۰۸/۲۳).

عاملِ گرهِ **واقعی** (پوشهٔ processing، نسخهٔ قدیمی 2.10 از تاریخچهٔ گیت) به‌صورت یک پردازشِ جدا اجرا می‌شود و با سایتِ واقعی
(LiveServerTestCase روی دیتابیسِ موقت) حرف می‌زند؛ حلقهٔ START.bat را یک اسکریپتِ کوچک تقلید می‌کند. می‌بینیم:
  ۱. عاملِ 2.10 وصل می‌شود؛ ۲. `autopilot.tick()` (بیتِ هر دقیقه) خودش دستورِ «update» را می‌فرستد و تا آن موقع کارِ تازه نمی‌دهد؛
  ۳. گره بستهٔ تازه را می‌گیرد، دوباره راه می‌افتد و با نسخهٔ تازه برمی‌گردد؛ ۴. سایت خودش یک اجرای آزمونِ پذیرش برای نسخهٔ تازه می‌سازد
  و گره (با عاملِ واقعی) کارهای واقعیِ آن را برمی‌دارد و انجام می‌دهد؛ ۵. کارهای منتظر (echo) در صف می‌مانند و بعد از به‌روزرسانی انجام می‌شوند.
روی لینوکس کارت و ویندوز نیست، پس آزمون‌های کارت «رد/ردشده» می‌شوند؛ آنچه سنجیده می‌شود پروتکلِ سایت ⇄ عامل است، نه سخت‌افزار.

اجرا (سنگین و چند دقیقه است، پیش‌فرض رد می‌شود):
    git -C /root/qasem-repo archive f241be1 processing-server | tar -x -C /root/stage/e2e/node210
    NM_E2E_NODE=1 NM_E2E_OLD_NODE=/root/stage/e2e/node210/processing-server python manage.py test apps.compute.tests_e2e_node --noinput
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from django.conf import settings
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from . import autopilot
from . import services as SV
from .models import ComputeJob, ComputeNode, NodeAuto, SelfTestRun
from .selftests import runner

ENABLED = os.environ.get("NM_E2E_NODE") == "1"
OLD_NODE = os.environ.get("NM_E2E_OLD_NODE", "")
# the temp folder exists only when the opt-in run is on (importing this module in every normal test run must leave nothing behind) and is removed
# again in tearDownClass; NM_E2E_KEEP=1 keeps it for inspection
TMP = Path(tempfile.mkdtemp(prefix="nm-e2e-")) if ENABLED else Path(tempfile.gettempdir()) / "nm-e2e-disabled"

WRAPPER = textwrap.dedent('''
    # START.bat in Python: the agent runs, update.py --agent-exited after each stop, again after a short pause, until STOP exists
    import os, subprocess, sys, time
    folder, stop = sys.argv[1], sys.argv[2]
    subprocess.call([sys.executable, "agent.py", "--prepare"], cwd=folder)
    while not os.path.exists(stop):
        rc = subprocess.call([sys.executable, "agent.py"], cwd=folder)
        subprocess.call([sys.executable, "update.py", "--agent-exited"], cwd=folder)
        print("wrapper: the agent stopped with code %s" % rc, flush=True)
        time.sleep(2)
''')


def agent_version(folder: Path) -> str:
    for line in (folder / "agent.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("VERSION = "):
            return line.split('"')[1]
    return ""


def kill_processes_in(folder) -> int:
    """SIGTERM (then SIGKILL) every process whose working directory is `folder` or below it - the node agent, its START.bat stand-in, update.py and the
    servers the agent started on its own (abagram, the voice/photo services ...; Linux /proc). Without this they outlive the test for days."""
    me, mine = str(os.getpid()), str(folder)
    hit = []
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        try:
            cwd = os.readlink("/proc/%s/cwd" % pid) if pid.isdigit() and pid != me else ""
        except OSError:
            continue
        if cwd == mine or cwd.startswith(mine + os.sep):
            hit.append(int(pid))
    for sig in (15, 9):
        for pid in hit:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        time.sleep(1.5)
    return len(hit)


@unittest.skipUnless(ENABLED and OLD_NODE and os.path.isdir(OLD_NODE), "opt-in: NM_E2E_NODE=1 and NM_E2E_OLD_NODE=<folder of agent 2.10>")
@override_settings(NM_DATA_DIR=TMP / "site-data", IS_TEST=True)
class MorningWithTheRealAgent(LiveServerTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        kill_processes_in(TMP)
        if os.environ.get("NM_E2E_KEEP") != "1":
            shutil.rmtree(TMP, ignore_errors=True)               # up to ~1.3 GB of downloaded models and unpacked packages

    def setUp(self):
        (TMP / "site-data").mkdir(parents=True, exist_ok=True)
        self.folder = TMP / "node"
        if self.folder.exists():
            shutil.rmtree(self.folder)
        shutil.copytree(OLD_NODE, self.folder)
        # what the owner's node really has: Update.bat's marker of the package the folder came from (an old id)
        (self.folder / ".nm-version.json").write_text(json.dumps({"version": "2.10", "id": "1f328a7e5b9b71430000000000000000"}), encoding="utf-8")
        self.node = ComputeNode.objects.create(name="e2e-node", last_seen=None)
        self.stop = TMP / "node-data" / "STOP"
        (TMP / "node-data").mkdir(exist_ok=True)
        if self.stop.exists():
            self.stop.unlink()
        self.log_path = TMP / "node.log"
        self.proc = None
        self.t0 = time.time()
        self.timeline = []

    def tearDown(self):
        try:
            self.stop.write_text("stop")
        except OSError:
            pass
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        kill_processes_in(self.folder)                  # the agent (started as `python agent.py`, relative) outlives the wrapper
        try:
            print("\n----- node log (last 60 lines) -----\n" + "\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]))
        except OSError:
            pass
        print("\n----- timeline -----\n" + "\n".join(self.timeline))

    def note(self, text):
        line = "%5.0fs  %s" % (time.time() - self.t0, text)
        self.timeline.append(line)
        print(line, flush=True)

    def start_node(self):
        env = dict(os.environ, NM_SITE=self.live_server_url, NM_TOKEN=self.node.token, NM_NODE=self.node.name, NM_DATA=str(TMP / "node-data"),
                   NM_DATA_POINTER=str(TMP / "pointer.txt"), NM_NO_MIGRATE="1", NM_SETUP_WAIT_S="5", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        env.pop("NM_AUTO_UPDATE", None)          # the panel's «update» runs `update.py --auto`, which does nothing when NM_AUTO_UPDATE=0
        (TMP / "wrapper.py").write_text(WRAPPER, encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, str(TMP / "wrapper.py"), str(self.folder), str(self.stop)], cwd=str(self.folder), env=env,
                                     stdout=open(self.log_path, "w", encoding="utf-8"), stderr=subprocess.STDOUT)

    def fresh(self):
        return ComputeNode.objects.get(pk=self.node.pk)

    def wait(self, what, cond, timeout, every=3.0, tick=True):
        end = time.time() + timeout
        while time.time() < end:
            if tick:
                try:
                    autopilot.tick()                       # the beat task of every minute (compute.tasks.maintenance), here every few seconds
                except Exception as e:  # noqa: BLE001
                    self.note("tick error: %r" % e)
            got = cond()
            if got:
                return got
            time.sleep(every)
        self.fail("timed out after %ds waiting for: %s" % (timeout, what))

    def test_the_whole_morning(self):
        new_version = agent_version(Path(settings.BASE_DIR).parent / "processing")
        self.assertNotEqual(new_version, "2.10")
        self.start_node()

        # 1. the old agent connects and is seen
        self.wait("the 2.10 agent's first heartbeat", lambda: self.fresh().capabilities.get("agent") == "2.10" and self.fresh().online, 120, tick=False)
        self.note("agent 2.10 connected; commands=%s" % self.fresh().capabilities.get("commands"))

        # 2. work that was parked while the node was off: nothing is handed out until the node has updated
        waiting = SV.enqueue("echo", {"n": "parked-before-update"}, dedupe=False, require_online=False)
        withheld = SV.claim(self.fresh())
        self.assertIsNone(withheld, "an out-of-date node must not be given work before it updated")
        self.assertTrue(autopilot.update_wanted(self.fresh())[0])
        self.wait("the autopilot's update command", lambda: (NodeAuto.of(self.fresh()).update_tries or 0) >= 1, 90, every=2)
        self.note("the site sent the update command by itself: %s" % NodeAuto.of(self.fresh()).update_note)

        # 3. the node downloads the package, restarts on it, comes back as the new agent
        self.wait("the node to come back as agent %s" % new_version,
                  lambda: self.fresh().capabilities.get("agent") == new_version and self.fresh().online, 420, every=4)
        caps = self.fresh().capabilities
        self.note("agent %s is back; code=%s kinds=%d bootstrap=%s" % (caps.get("agent"), caps.get("code"), len(caps.get("kinds") or []),
                                                                 (caps.get("bootstrap") or {}).get("summary")))
        self.assertIn("up3d.render", caps.get("kinds") or [])
        self.assertIn("motion.render", caps.get("kinds") or [])
        self.assertEqual((caps.get("code") or {}).get("id"), (autopilot.U.latest() or {}).get("id", "")[:16])
        self.assertFalse(autopilot.update_wanted(self.fresh())[0], "the site still thinks the node is out of date")

        # 4. the site made one acceptance run for the NEW version (none for the old one) and the real agent works through it
        run = self.wait("an acceptance run for the new version", lambda: SelfTestRun.objects.filter(node=self.node).order_by("-id").first(), 120, every=3)
        self.assertEqual(run.agent_version, new_version)
        self.assertEqual(run.trigger, "version")
        self.note("acceptance run #%s (%s) started" % (run.pk, run.trigger))

        def finished():
            r = SelfTestRun.objects.get(pk=run.pk)
            return r if r.state != "RUNNING" else None
        done = self.wait("the acceptance run to finish", finished, 900, every=5)
        rows = {r.key: r for r in done.results.all()}
        self.note("run %s: %s" % (done.state, ", ".join("%s=%s" % (k, r.state) for k, r in sorted(rows.items()))))
        self.assertEqual(rows["echo"].state, "PASSED", rows["echo"].detail)

        # 5. the echo job parked before the update was done by the new agent
        job = ComputeJob.objects.get(pk=waiting.pk)
        self.assertEqual(job.state, "COMPLETED", "the job parked before the update did not run afterwards: %s %s" % (job.state, job.error))
        self.note("the job parked before the update ran on the new agent (node=%s)" % job.node)

    @unittest.skipUnless(os.environ.get("NM_E2E_KEYS"), "diagnostic: NM_E2E_KEYS=photo_edit,photo_analyze runs only those self-tests with the real agent")
    def test_selected_selftests(self):
        """Run: ... manage.py test apps.compute.tests_e2e_node.MorningWithTheRealAgent.test_selected_selftests  (NM_E2E_KEYS=key1,key2).
        The real agent updates from 2.10 first; then one manual run of just those tests; every result and job is printed."""
        keys = [k for k in os.environ["NM_E2E_KEYS"].split(",") if k]
        new_version = agent_version(Path(settings.BASE_DIR).parent / "processing")
        self.start_node()
        self.wait("the 2.10 agent", lambda: self.fresh().capabilities.get("agent") == "2.10" and self.fresh().online, 120, tick=False)
        self.wait("the update", lambda: self.fresh().capabilities.get("agent") == new_version and self.fresh().online, 420, every=4)
        caps = self.fresh().capabilities
        self.note("caps: photo=%s startable=%s auto_switch=%s kinds=%s" % (caps.get("photo"), caps.get("startable"), caps.get("auto_switch"), len(caps.get("kinds") or [])))
        SelfTestRun.objects.filter(node=self.node, state="RUNNING").update(state="ABORTED")      # the acceptance run of the new version is not wanted here
        run = runner.start_run(self.node, "manual", only=keys)
        end = time.time() + int(os.environ.get("NM_E2E_WAIT", "240"))
        while time.time() < end:
            runner.advance(run)
            run.refresh_from_db()
            self.note("results: %s" % {r.key: (r.state, r.detail[:160]) for r in run.results.all()})
            for j in ComputeJob.objects.filter(origin="selftest").order_by("-id")[:4]:
                self.note("  job %s %s state=%s msg=%s err=%s" % (str(j.uid)[:8], j.kind, j.state, (j.message or "")[:80], (j.error or "")[:240]))
            if run.state != "RUNNING":
                break
            time.sleep(15)
        self.note("final: %s" % {r.key: (r.state, r.detail[:400]) for r in run.results.all()})
