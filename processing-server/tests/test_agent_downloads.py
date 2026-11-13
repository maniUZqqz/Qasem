"""agent.py 2.6: downloads on a schedule, the durable-queue robustness, the numbers for the report page and the banner.

    python -m unittest tests/test_agent_downloads.py        (from the processing folder; Windows and Linux)

Everything runs on a FAKE CLOCK (agent._now) and a fake site / fake downloader process - no real waiting, no internet.
Covers: the window maths (Tehran = UTC+3:30, fixed offset, midnight-crossing windows, a skewed PC clock), what the site's
answer stores and where it is kept, the download manager (waits outside the window, pauses cleanly when it closes - not a
failure -, resumes by itself, a job's own window beats the global one), the editors deferred in the background but never for
a job, background_setup waiting for the first answer, ollama.pull waiting inside the job (lease kept alive, lock released,
cancel) and stopping when the window closes mid-pull, finish() / upload retries, the work-folder sweep, the heartbeat numbers
(disk, GPU) and the banner.
"""
import calendar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))   # never the real data folder
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import agent  # noqa: E402
from test_agent_ollama_pull import OL, FakeSite as PullSite, OllamaHandler, TOTAL  # noqa: E402

DAY = 86400


def tehran(hour, minute=0, day=0, second=0):
    """The epoch second at which the wall clock in Tehran (UTC+3:30) shows hour:minute on 2026-11-07 (+day)."""
    return calendar.timegm((2026, 11, 7, hour, minute, second)) + day * DAY - agent.TZ_OFFSET_S


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class Base(unittest.TestCase):
    """A clean STATE, a private data folder and a fake clock for each test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-agent-dl-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = Clock(tehran(12))
        self.real_now = agent._now
        keep = {k: agent.STATE.get(k) for k in ("downloads", "clock_skew_s", "site_version")}
        for name, value in {"DATA": self.tmp, "LOGS": os.path.join(self.tmp, "logs"), "WORK": os.path.join(self.tmp, "work"),
                            "_now": self.clock.now}.items():
            p = mock.patch.object(agent, name, value)
            p.start()
            self.addCleanup(p.stop)
        for k in keep:
            agent.STATE.pop(k, None)

        def restore():
            for k in keep:
                agent.STATE.pop(k, None)
            agent.STATE.update({k: v for k, v in keep.items() if v is not None})
        self.addCleanup(restore)
        self.lines = []
        p = mock.patch.object(agent, "log", lambda msg, level="INFO": self.lines.append((level, msg)))
        p.start()
        self.addCleanup(p.stop)
        agent.SITE_LOG.buf = []
        self.addCleanup(lambda: setattr(agent.SITE_LOG, "buf", []))

    def window(self, mode="window", window="02:00-07:00"):
        agent.STATE["downloads"] = {"mode": mode, "window": window}


# ───────────────────────────────────────────── the window maths

class WindowMathTests(Base):
    def test_parse(self):
        self.assertEqual(agent.parse_window("02:00-07:00"), (120, 420))
        self.assertEqual(agent.parse_window(" 2:30 - 7:05 ".replace(" ", "")), (150, 425))
        for bad in ("", None, "07:00-07:00", "25:00-07:00", "02:00", "a-b", "02:00-07:61", "-"):
            self.assertIsNone(agent.parse_window(bad), repr(bad))

    def test_inside_and_outside(self):
        w = "02:00-07:00"
        for hour, minute, want in ((1, 59, False), (2, 0, True), (4, 30, True), (6, 59, True), (7, 0, False), (12, 0, False), (23, 59, False)):
            self.assertEqual(agent.in_window(w, tehran(hour, minute)), want, "%02d:%02d" % (hour, minute))

    def test_a_window_that_crosses_midnight(self):
        w = "22:00-04:00"
        for hour, minute, want in ((21, 59, False), (22, 0, True), (23, 59, True), (0, 0, True), (3, 59, True), (4, 0, False), (12, 0, False)):
            self.assertEqual(agent.in_window(w, tehran(hour, minute)), want, "%02d:%02d" % (hour, minute))
        self.assertEqual(agent.seconds_to_window(w, tehran(12)), 10 * 3600)

    def test_seconds_until_the_window_opens(self):
        w = "02:00-07:00"
        self.assertEqual(agent.seconds_to_window(w, tehran(1)), 3600)
        self.assertEqual(agent.seconds_to_window(w, tehran(1, 59, second=30)), 30)
        self.assertEqual(agent.seconds_to_window(w, tehran(3)), 0)
        self.assertEqual(agent.seconds_to_window(w, tehran(7)), 19 * 3600)
        self.assertEqual(agent.seconds_to_window(w, tehran(12)), 14 * 3600)
        self.assertEqual(agent.seconds_to_window("", tehran(12)), 0)

    def test_the_offset_is_fixed_no_daylight_saving(self):
        summer = calendar.timegm((2026, 7, 1, 10, 0, 0))          # 10:00 UTC = 13:30 in Tehran, in July as in November
        self.assertTrue(agent.in_window("13:00-14:00", summer))
        self.assertFalse(agent.in_window("14:00-15:00", summer))
        winter = calendar.timegm((2026, 1, 1, 10, 0, 0))
        self.assertTrue(agent.in_window("13:00-14:00", winter))
        self.assertEqual(agent.hhmm_tehran(summer), "13:30")

    def test_the_window_only_applies_in_window_mode_or_when_a_job_carries_its_own(self):
        self.assertTrue(agent.download_allowed(tehran(12)), "no settings at all = any time")
        self.window("now")
        self.assertTrue(agent.download_allowed(tehran(12)), "mode now ignores the saved window")
        self.window("window")
        self.assertFalse(agent.download_allowed(tehran(12)))
        self.assertTrue(agent.download_allowed(tehran(3)))
        self.assertTrue(agent.download_allowed(tehran(12), window=""), "a job that says «now» is not held by the global window")
        self.assertFalse(agent.download_allowed(tehran(12), window="01:00-05:00"))
        self.window("now")
        self.assertFalse(agent.download_allowed(tehran(12), window="01:00-05:00"), "a job's own window holds even in mode now")
        self.assertEqual(agent.seconds_until_window(tehran(12), window="13:00-14:00"), 3600)

    def test_the_sites_clock_is_this_computers_clock_plus_the_skew(self):
        self.window()
        with mock.patch.object(agent, "_now", self.real_now), mock.patch.object(agent.time, "time", lambda: tehran(12)):
            self.assertEqual(agent._now(), tehran(12))
            self.assertFalse(agent.download_allowed())
            agent.STATE["clock_skew_s"] = 14 * 3600                  # this PC runs 14 h behind the site: there it is 02:00
            self.assertEqual(agent._now(), tehran(12) + 14 * 3600)
            self.assertTrue(agent.download_allowed())

    def test_persian_clock_text(self):
        now = tehran(12)
        self.assertEqual(agent.fa_clock(tehran(15, 30), now), "امروز ۱۵:۳۰")
        self.assertEqual(agent.fa_clock(tehran(2, 0, day=1), now), "فردا ۰۲:۰۰")
        self.assertEqual(agent.fa_clock(tehran(2, 0, day=3), now), "۳ روزِ دیگر، ۰۲:۰۰")


# ───────────────────────────────────────────── what the site says

class ControlTests(Base):
    def setUp(self):
        super().setUp()
        agent.FIRST_CONTROL.clear()
        self.addCleanup(agent.FIRST_CONTROL.set)         # later tests must never wait for a first answer
        self.titles = []
        p = mock.patch.object(agent, "set_console_title", lambda text: self.titles.append(text) or True)
        p.start()
        self.addCleanup(p.stop)

    def answer(self, mode="window", window="02:00-07:00", server_time=None, version="2.60"):
        r = {"ok": True, "downloads": {"mode": mode, "window": window, "tz_offset_min": 210,
                                       "server_time": server_time or datetime.fromtimestamp(self.clock.t, timezone.utc).isoformat()}}
        if version:
            r["site_version"] = version
        return r

    def test_the_answer_is_stored_and_saved(self):
        agent.absorb_control(self.answer())
        self.assertEqual(agent.STATE["downloads"], {"mode": "window", "window": "02:00-07:00"})
        self.assertEqual(agent.STATE["site_version"], "2.60")
        self.assertTrue(agent.FIRST_CONTROL.is_set())
        saved = json.load(open(agent.window_file(), encoding="utf-8"))
        self.assertEqual((saved["mode"], saved["window"]), ("window", "02:00-07:00"))
        self.assertFalse(agent.download_allowed(tehran(12)))

    def test_an_agent_restarted_while_the_site_is_unreachable_still_knows_the_window(self):
        agent.absorb_control(self.answer(window="01:30-05:00"))
        agent.STATE.pop("downloads")                                       # a new process: nothing in memory
        self.assertEqual(agent.load_download_settings(), {"mode": "window", "window": "01:30-05:00"})
        self.assertFalse(agent.download_allowed(tehran(12)))
        self.assertTrue(agent.download_allowed(tehran(2)))

    def test_a_missing_or_broken_file_is_ignored(self):
        self.assertIsNone(agent.load_download_settings())
        os.makedirs(agent.DATA, exist_ok=True)
        open(agent.window_file(), "w").write("{not json")
        self.assertIsNone(agent.load_download_settings())
        self.assertTrue(agent.download_allowed(tehran(12)))

    def test_an_older_site_sends_nothing_and_the_saved_settings_stay(self):
        agent.absorb_control(self.answer())
        agent.absorb_control({"ok": True, "desired": {}, "auto_switch": True})
        self.assertEqual(agent.STATE["downloads"]["mode"], "window")
        agent.absorb_control("garbage")
        agent.absorb_control(None)
        self.assertEqual(agent.STATE["downloads"]["mode"], "window")

    def test_a_broken_window_in_the_answer_falls_back_to_the_default(self):
        agent.absorb_control(self.answer(window="garbage"))
        self.assertEqual(agent.STATE["downloads"]["window"], agent.DEFAULT_WINDOW)
        agent.absorb_control(self.answer(mode="whatever"))
        self.assertEqual(agent.STATE["downloads"]["mode"], "now")

    def test_the_file_is_written_once_per_change(self):
        agent.absorb_control(self.answer())
        os.utime(agent.window_file(), (1, 1))
        agent.absorb_control(self.answer())
        self.assertEqual(os.stat(agent.window_file()).st_mtime, 1, "same settings: no rewrite")
        agent.absorb_control(self.answer(mode="now"))
        self.assertGreater(os.stat(agent.window_file()).st_mtime, 1)

    def test_the_sites_clock_corrects_a_wrong_pc_clock(self):
        real = time.time()
        site = datetime.fromtimestamp(real + 5 * 3600, timezone.utc).isoformat()       # the PC is 5 h behind
        agent.absorb_control(self.answer(server_time=site))
        self.assertAlmostEqual(agent.STATE["clock_skew_s"], 5 * 3600, delta=5)
        far = datetime.fromtimestamp(real + 30 * DAY, timezone.utc).isoformat()
        agent.absorb_control(self.answer(server_time=far))
        self.assertEqual(agent.STATE["clock_skew_s"], 0.0, "an absurd difference is ignored")
        agent.absorb_control({"server_time": datetime.fromtimestamp(real + 60, timezone.utc).isoformat()})   # heartbeat's own key
        self.assertAlmostEqual(agent.STATE["clock_skew_s"], 60, delta=5)

    def test_version_banner_and_title(self):
        self.assertEqual(agent.banner_text(), "NMarketing processing node v%s" % agent.VERSION)
        agent.absorb_control(self.answer(version="2.60"))
        self.assertEqual(agent.banner_text(), "NMarketing processing node v%s (site v2.60)" % agent.VERSION)
        self.assertEqual(self.titles, [agent.banner_text()])
        agent.absorb_control(self.answer(version="2.60"))
        self.assertEqual(len(self.titles), 1, "the title is set when the site's version becomes known, not on every answer")
        self.assertTrue(all(ord(ch) < 128 for _lvl, msg in self.lines for ch in msg), "the console stays ASCII")

    def test_first_answer_event_and_waiting_for_it(self):
        self.assertFalse(agent.wait_first_control(0.01))
        agent.absorb_control({"ok": True})
        self.assertTrue(agent.wait_first_control(0.01))


class ConsoleTitleTests(unittest.TestCase):
    def test_title_only_on_windows_and_never_raises(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(agent.set_console_title("x"))
        calls = []
        fake_kernel = mock.Mock()
        fake_kernel.SetConsoleTitleW = lambda text: calls.append(text)
        fake_ctypes = mock.Mock(windll=mock.Mock(kernel32=fake_kernel))
        with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(sys.modules, {"ctypes": fake_ctypes}):
            self.assertTrue(agent.set_console_title("NMarketing processing node v2.6"))
        self.assertEqual(calls, ["NMarketing processing node v2.6"])
        broken = mock.Mock()
        type(broken).windll = mock.PropertyMock(side_effect=OSError("no console"))
        with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(sys.modules, {"ctypes": broken}):
            self.assertFalse(agent.set_console_title("x"))

    def test_version_flag_prints_the_banner(self):
        env = dict(os.environ, NM_DATA=tempfile.mkdtemp(prefix="nm-ver-"), PYTHONIOENCODING="utf-8")
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "agent.py"), "--version"], capture_output=True,
                             text=True, timeout=60, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "NMarketing processing node v%s" % agent.VERSION)
        self.assertEqual(agent.VERSION, "2.12")


# ───────────────────────────────────────────── the background model download

class FakeProc:
    made = []

    def __init__(self, cmd, **kw):
        self.cmd, self.pid, self.code, self.terminated = cmd, 700 + len(FakeProc.made), None, False
        FakeProc.made.append(self)

    def poll(self):
        return self.code

    @property
    def returncode(self):
        return self.code

    def terminate(self):
        self.terminated, self.code = True, -15

    def kill(self):
        self.code = -9

    def wait(self, timeout=None):
        return self.code


class DownloadManagerTests(Base):
    def setUp(self):
        super().setUp()
        FakeProc.made = []
        os.makedirs(agent.LOGS, exist_ok=True)
        script = os.path.join(self.tmp, "download_models.py")
        open(script, "w").write("# stand-in\n")
        for target, value in (("DOWNLOADER", script), ):
            p = mock.patch.object(agent, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(agent.subprocess, "Popen", FakeProc)
        p.start()
        self.addCleanup(p.stop)

        def fake_run(cmd, *a, **kw):                      # the Windows way to stop a process tree
            if cmd and cmd[0] == "taskkill":
                for proc in FakeProc.made:
                    if str(proc.pid) in cmd:
                        proc.code = 1
            return subprocess.CompletedProcess(cmd, 0, "", "")
        p = mock.patch.object(agent.subprocess, "run", fake_run)
        p.start()
        self.addCleanup(p.stop)
        self.dm = agent.DownloadManager()
        self.dm.refresh = lambda force=False: None

    def test_outside_the_window_a_request_waits_and_the_panel_is_told(self):
        self.window()
        self.assertEqual(self.dm.start(None, "found missing at start-up"), "waiting")
        self.assertEqual(FakeProc.made, [], "no process is started outside the window")
        caps = self.dm.caps()
        self.assertFalse(caps["running"])
        self.assertEqual(caps["error"], "")
        w = caps["waiting"]
        self.assertTrue(w["default"])
        self.assertEqual(w["reason"], "window")
        self.assertEqual(agent._iso_epoch(w["until"]), tehran(2, 0, day=1), "it says when the window opens")
        self.assertTrue(any("بازهٔ دانلود" in e["message"] for e in agent.SITE_LOG.buf), "the panel's log says it waits (Persian)")
        self.assertTrue(all(ord(ch) < 128 for _l, m in self.lines for ch in m), "console lines stay ASCII")

    def test_it_starts_by_itself_when_the_window_opens(self):
        self.window()
        self.dm.start(["fun-inp"], "asked from the panel")
        self.dm.poll()
        self.assertEqual(FakeProc.made, [])
        self.clock.t = tehran(1, 59)
        self.dm.poll()
        self.assertEqual(FakeProc.made, [])
        self.clock.t = tehran(2, 0)
        self.dm.poll()
        self.assertEqual(len(FakeProc.made), 1)
        cmd = FakeProc.made[0].cmd
        self.assertEqual(cmd[cmd.index("--only") + 1], "fun-inp")
        self.assertIsNone(self.dm.caps().get("waiting"), "nothing waits any more")
        self.assertTrue(self.dm.running())

    def test_inside_the_window_it_starts_at_once_as_before(self):
        self.window()
        self.clock.t = tehran(3)
        self.assertEqual(self.dm.start(None), "started")
        self.assertEqual(self.dm.start(["b"]), "queued")
        self.assertEqual(len(FakeProc.made), 1)

    def test_no_window_set_nothing_changes(self):
        self.assertEqual(self.dm.start(None), "started")
        self.dm.poll()
        self.assertIsNone(FakeProc.made[0].poll())

    def test_a_run_is_paused_cleanly_when_the_window_closes_and_resumes_by_itself(self):
        self.window()
        self.clock.t = tehran(5)
        self.dm.start(["moss-tts", "fun-inp"], "asked from the panel")
        proc = FakeProc.made[0]
        self.dm.poll()
        self.assertIsNone(proc.poll(), "still inside the window")
        self.clock.t = tehran(7, 0)
        self.dm.poll()
        self.assertIsNotNone(proc.poll(), "the download process was stopped")
        self.assertIsNone(self.dm.proc)
        self.assertEqual(self.dm.last_error, "", "pausing is not a failure")
        self.assertEqual(self.dm.retry_at, 0.0, "no one-hour failure path")
        self.assertFalse(any(level in ("WARNING", "ERROR") for level, _m in self.lines), self.lines)
        caps = self.dm.caps()
        self.assertFalse(caps["running"])
        self.assertEqual(caps["waiting"]["packages"], ["fun-inp", "moss-tts"])
        self.assertEqual(agent._iso_epoch(caps["waiting"]["until"]), tehran(2, 0, day=1))
        self.clock.t = tehran(23)
        self.dm.poll()
        self.assertEqual(len(FakeProc.made), 1, "still closed")
        self.clock.t = tehran(2, 0, day=1)
        self.dm.poll()
        self.assertEqual(len(FakeProc.made), 2, "resumed in the next window")
        again = FakeProc.made[1].cmd
        self.assertEqual(again[again.index("--only") + 1], "fun-inp,moss-tts")
        self.assertIsNone(self.dm.caps().get("waiting"))

    def test_a_job_that_says_now_is_not_held_by_the_global_window(self):
        self.window()
        self.assertEqual(self.dm.start(["fun-inp"], "asked from the panel", window=""), "started")
        self.dm.poll()
        self.assertIsNone(FakeProc.made[0].poll(), "its own window is «no limit»: it keeps running")
        self.assertEqual(self.dm.run_window, "")

    def test_a_job_with_its_own_window_follows_it(self):
        self.window("now")
        self.clock.t = tehran(12)
        self.assertEqual(self.dm.start(["fun-inp"], "asked from the panel", window="13:00-14:00"), "waiting")
        self.clock.t = tehran(13, 0)
        self.dm.poll()
        self.assertEqual(len(FakeProc.made), 1)
        self.clock.t = tehran(14, 0)
        self.dm.poll()
        self.assertIsNotNone(FakeProc.made[0].poll(), "stopped when its own window closed")

    def test_a_finished_run_in_the_window_still_works_as_before(self):
        self.window()
        self.clock.t = tehran(3)
        self.dm.start(None)
        FakeProc.made[0].code = 0
        self.dm.poll()
        self.assertIsNone(self.dm.proc)
        self.assertEqual(self.dm.retry_at, 0.0)
        self.assertTrue(any("download finished" in m for _l, m in self.lines))

    def test_a_real_failure_keeps_the_hourly_retry_but_the_retry_waits_for_the_window(self):
        self.window()
        self.clock.t = tehran(3)
        self.dm.start(None)
        FakeProc.made[0].code = 2
        self.dm.poll()
        self.assertTrue(self.dm.last_error.startswith("download ended with code 2"))
        self.assertGreater(self.dm.retry_at, 0)
        self.dm.missing_default = lambda: ["moss-tts"]
        self.clock.t = tehran(9)                                 # window closed when the hour is up
        self.dm.retry_at = time.time() - 1
        self.dm.poll()
        self.assertEqual(len(FakeProc.made), 1, "the retry did not start outside the window")
        self.assertTrue(self.dm.waiting())
        self.clock.t = tehran(2, 0, day=1)
        self.dm.poll()
        self.assertEqual(len(FakeProc.made), 2)

    def test_a_job_is_told_to_try_again_while_its_model_waits_for_the_window(self):
        self.window()
        self.dm.start(["moss-tts"], "asked from the panel")
        self.assertTrue(self.dm.waiting_for("moss-tts"))
        self.assertFalse(self.dm.waiting_for("fun-inp"))
        self.assertFalse(self.dm.downloading("moss-tts"))
        self.assertEqual(self.dm.percent_text(), "waiting for the download window")
        with mock.patch.object(agent, "DOWNLOADS", self.dm), mock.patch.object(agent, "audio_installed", lambda key: False):
            with self.assertRaises(agent.JobError) as ctx:
                with mock.patch.object(agent, "find_comfy_start", lambda: None):
                    mgr = agent.ServiceManager()
                mgr.prepare_audio("moss", True)
        self.assertIn("DOWNLOADING", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)

    def test_the_panel_job_passes_its_own_window_to_the_manager(self):
        fake = mock.Mock()
        fake.start.return_value = "started"
        fake.caps.return_value = {}
        for payload, want in (({"action": "download", "packages": ["a"]}, None),
                              ({"action": "download", "packages": ["a"], "window": ""}, ""),
                              ({"action": "download", "packages": ["a"], "window": "02:00-07:00"}, "02:00-07:00")):
            fake.start.reset_mock()
            job = agent.Job(mock.Mock(), {"uid": "m1", "kind": "node.models", "payload": payload})
            os.makedirs(job.outputs, exist_ok=True)
            with mock.patch.object(agent, "DOWNLOADS", fake):
                agent.h_node_models(job)
            self.assertEqual(fake.start.call_args.kwargs["window"], want, payload)


# ───────────────────────────────────────────── editors and the start-up setup

class EditorTests(Base):
    def run_editor(self, key, background, published=False, ffmpeg=False, voice=True, photo_model=False):
        fetched, built = [], []
        os.makedirs(os.path.join(self.tmp, "tools", "PersianAiKit", agent.KIT_DIRS[key], "src"), exist_ok=True)
        state = {"published": published}

        def fetch(name, tick=None):
            fetched.append(name)
            state["published"] = True
            return 1
        with mock.patch.object(agent, "editor_published", lambda k: state["published"]), \
                mock.patch.object(agent, "find_dotnet", lambda: None), mock.patch.object(agent, "ffmpeg_ok", lambda: ffmpeg), \
                mock.patch.object(agent, "voice_models_ok", lambda: voice), mock.patch.object(agent, "fetch_pack", fetch), \
                mock.patch.object(agent, "run_logged", lambda *a, **k: built.append(a) or False):
            try:
                agent.ensure_editor(key, background=background)
                err = None
            except agent.DownloadDeferred as e:
                err = e
        return fetched, built, err

    def test_background_editor_download_waits_outside_the_window(self):
        self.window()
        fetched, _built, err = self.run_editor("voice", background=True)
        self.assertIsInstance(err, agent.DownloadDeferred)
        self.assertEqual(fetched, [], "nothing was downloaded")
        self.assertIn("download window", str(err))

    def test_a_job_that_needs_the_editor_is_never_delayed(self):
        self.window()
        fetched, _built, err = self.run_editor("voice", background=False)
        self.assertIsNone(err)
        self.assertEqual(fetched, [agent.KIT_APP_PACK["voice"]])

    def test_background_editor_inside_the_window_downloads(self):
        self.window()
        self.clock.t = tehran(3)
        fetched, _built, err = self.run_editor("voice", background=True)
        self.assertIsNone(err)
        self.assertEqual(fetched, [agent.KIT_APP_PACK["voice"]])

    def test_ffmpeg_and_voice_models_of_a_built_editor_wait_too(self):
        self.window()
        fetched, _b, err = self.run_editor("video", background=True, published=True, ffmpeg=False)
        self.assertIsInstance(err, agent.DownloadDeferred)
        self.assertEqual(fetched, [])
        fetched, _b, err = self.run_editor("voice", background=True, published=True, voice=False)
        self.assertIsInstance(err, agent.DownloadDeferred)
        self.assertEqual(fetched, [])
        fetched, _b, err = self.run_editor("video", background=False, published=True, ffmpeg=False)
        self.assertEqual(fetched, ["kit-ffmpeg.zip"], "a job gets its ffmpeg at once")

    def test_the_optional_photo_upscaler_is_skipped_not_deferred(self):
        self.window()
        fetched, _b, err = self.run_editor("photo", background=True, published=True)
        self.assertIsNone(err, "the built photo editor can start without its optional model")
        self.assertEqual(fetched, [])
        fetched, _b, err = self.run_editor("photo", background=False, published=True)
        self.assertEqual(fetched, ["kit-models-photo.zip"])

    def test_no_window_means_nothing_is_deferred(self):
        fetched, _b, err = self.run_editor("voice", background=True)
        self.assertIsNone(err)
        self.assertEqual(fetched, [agent.KIT_APP_PACK["voice"]])

    def make_manager(self):
        with mock.patch.object(agent, "find_comfy_start", lambda: None):
            m = agent.ServiceManager()
        m.running = lambda key: False
        m._command = lambda key: "run-%s.bat" % key
        return m

    def test_the_panel_started_service_does_not_block_the_main_loop_for_a_download(self):
        self.window()
        m = self.make_manager()
        os.makedirs(os.path.join(self.tmp, "tools", "PersianAiKit", "Video", "src"), exist_ok=True)
        popen = mock.Mock(side_effect=AssertionError("must not start"))
        with mock.patch.object(agent.subprocess, "Popen", popen), mock.patch.object(agent, "editor_published", lambda k: False), \
                mock.patch.object(agent, "find_dotnet", lambda: None):
            self.assertFalse(m.start("video", background=True))
            self.assertFalse(m.start("video", background=True))
        self.assertEqual(len([1 for lvl, msg in self.lines if "download window" in msg]), 1, "said once, not on every heartbeat")
        self.assertFalse(any(lvl == "ERROR" for lvl, _m in self.lines))

    def test_apply_marks_the_panels_start_as_background_and_a_job_start_is_not(self):
        m = self.make_manager()
        calls = []
        m.start = lambda key, wait=True, tick=None, background=False: calls.append((key, background)) or True
        m.apply({"video": True})
        self.assertEqual(calls, [("video", True)])
        seen = []
        with mock.patch.object(agent, "ensure_editor", lambda key, tick=None, background=False: seen.append(background) or True):
            m2 = self.make_manager()
            m2.cfg = {"video": {"start": "run.bat", "url": "NM_VIDEO_URL"}}
            with mock.patch.object(agent.subprocess, "Popen", lambda *a, **k: mock.Mock(poll=lambda: 0)),                     mock.patch.object(agent, "find_dotnet", lambda: None):
                m2.start("video", wait=False, tick=lambda msg: None)
        self.assertEqual(seen, [False], "prepare_for (a job) starts it with background=False")


class BackgroundSetupTests(Base):
    def setUp(self):
        super().setUp()
        self.events = []
        self.dl = mock.Mock()
        self.dl.available.return_value = True
        self.dl.missing_default.return_value = ["moss-tts"]
        self.dl.running.return_value = False
        self.dl.start.side_effect = lambda *a, **k: self.events.append(("download", a, k)) or "waiting"
        for name, value in (("DOWNLOADS", self.dl), ("wait_first_control", lambda timeout=None: self.events.append(("first",)) or True),
                            ("_editor_needs_work", lambda key: key == "video")):
            p = mock.patch.object(agent, name, value)
            p.start()
            self.addCleanup(p.stop)

    def fake_editor(self, key, tick=None, background=False):
        self.events.append(("editor", key, background, agent.download_allowed()))
        if background and not agent.download_allowed():
            raise agent.DownloadDeferred("%s editor: waits for the download window" % key)
        return True

    def test_it_waits_for_the_first_answer_then_defers_outside_the_window_and_finishes_inside_it(self):
        self.window()                                                     # 12:00: closed
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            self.clock.advance(seconds)
        with mock.patch.object(agent, "ensure_editor", self.fake_editor):
            agent.background_setup(sleep=sleep)
        self.assertEqual(self.events[0], ("first",), "it decides only after the first answer of the site")
        editors = [e for e in self.events if e[0] == "editor"]
        self.assertEqual(editors[0], ("editor", "video", True, False), "background=True: it is not a job")
        self.assertEqual(editors[-1][3], True, "the editor was finally prepared inside the window")
        self.assertGreaterEqual(sum(slept), 14 * 3600 - 60)
        self.assertTrue(all(s <= 60 for s in slept), "it wakes up often (a changed setting is noticed)")
        downloads = [e for e in self.events if e[0] == "download"]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0][1][0], None, "the default model set is handed to the manager (it waits by itself)")

    def test_no_window_it_behaves_as_before(self):
        slept = []
        with mock.patch.object(agent, "ensure_editor", self.fake_editor):
            agent.background_setup(sleep=slept.append)
        self.assertEqual(slept, [])
        self.assertEqual([e[0] for e in self.events], ["first", "editor", "download"])

    def test_a_setting_that_changes_to_now_releases_the_waiting_editor(self):
        self.window()

        def sleep(seconds):
            agent.STATE["downloads"] = {"mode": "now", "window": "02:00-07:00"}      # the owner changed the setting meanwhile
        with mock.patch.object(agent, "ensure_editor", self.fake_editor):
            agent.background_setup(sleep=sleep)
        self.assertTrue([e for e in self.events if e[0] == "editor"][-1][3])

    def test_a_broken_editor_does_not_stop_the_download(self):
        def boom(key, tick=None, background=False):
            raise RuntimeError("dotnet exploded")
        with mock.patch.object(agent, "ensure_editor", boom):
            agent.background_setup(sleep=lambda s: None)
        self.assertEqual(len(self.dl.start.call_args_list), 1)
        self.assertTrue(any(lvl == "WARNING" for lvl, _m in self.lines))


# ───────────────────────────────────────────── ollama.pull inside the job

class PullWindowTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls._old_url = os.environ.get("NM_OLLAMA_URL")
        os.environ["NM_OLLAMA_URL"] = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        if cls._old_url is None:
            os.environ.pop("NM_OLLAMA_URL", None)
        else:
            os.environ["NM_OLLAMA_URL"] = cls._old_url

    def setUp(self):
        super().setUp()
        OL.reset()
        os.environ["NM_PULL_REPORT_S"] = "0"
        self.addCleanup(os.environ.pop, "NM_PULL_REPORT_S", None)
        agent.CONFIG = {"name": "TEST-NODE"}
        self.slept = []
        self.lock_free_while_waiting = []

        def sleep(seconds):
            self.slept.append(seconds)
            self.lock_free_while_waiting.append(not agent.PULL_LOCK.locked())
            self.clock.advance(seconds)
        p = mock.patch.object(agent, "_window_sleep", sleep)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(agent, "_pull_pause", lambda tracker, seconds: tracker.report(force=True))
        p.start()
        self.addCleanup(p.stop)

    def job(self, site=None, **payload):
        site = site or PullSite()
        body = {"tag": "gemma3:12b", "expected_bytes": TOTAL + 100, **payload}
        site.payload = body
        j = agent.Job(site, {"uid": "w%08x" % id(site), "kind": "ollama.pull", "payload": body})
        j.fetch()
        return j, site

    def progress(self, site):
        return [d for p, d in site.posts if p.endswith("/progress/") and d]

    def test_a_pull_for_the_night_waits_keeping_its_lease_alive_then_downloads(self):
        self.clock.t = tehran(1, 0)
        j, site = self.job(window="02:00-07:00")
        meta = agent.h_ollama_pull(j)
        self.assertEqual(meta["attempts"], 1)
        self.assertIn("gemma3:12b", OL.models)
        self.assertEqual(sum(self.slept), 3600, "it waited exactly until 02:00")
        self.assertTrue(all(s <= 25 for s in self.slept), "a progress call at least every 25 s keeps the lease alive")
        waiting = [d for d in self.progress(site) if (d.get("meta") or {}).get("phase") == "window"]
        self.assertGreaterEqual(len(waiting), 3600 // 25)
        self.assertTrue(all("منتظرِ بازهٔ دانلود" in d["message"] for d in waiting))
        self.assertEqual(waiting[0]["meta"]["resume_text"], "ادامه امروز ۰۲:۰۰")
        self.assertEqual(agent._iso_epoch(waiting[0]["meta"]["resume_at"]), tehran(2, 0))
        self.assertTrue(all(self.lock_free_while_waiting), "the download line is not held while waiting")
        self.assertEqual(len(OL.pulls), 1)

    def test_the_global_window_holds_a_pull_without_its_own_window(self):
        self.window()
        self.clock.t = tehran(12)
        j, site = self.job()
        agent.h_ollama_pull(j)
        self.assertEqual(sum(self.slept), 14 * 3600)

    def test_a_job_that_says_now_downloads_at_once_even_in_a_closed_window(self):
        self.window()
        self.clock.t = tehran(12)
        j, site = self.job(window="")
        agent.h_ollama_pull(j)
        self.assertEqual(self.slept, [])
        self.assertIn("gemma3:12b", OL.models)

    def test_an_old_site_without_window_in_the_payload_downloads_now(self):
        self.clock.t = tehran(12)
        j, _site = self.job()
        agent.h_ollama_pull(j)
        self.assertEqual(self.slept, [])

    def test_the_window_closing_mid_pull_stops_the_stream_and_continues_in_the_next_window(self):
        ticks = {"n": 0}

        def moving_clock():                      # 06:59:50, and every look at the clock costs 3 s
            if not self.slept:
                ticks["n"] += 1
                return tehran(6, 59, second=50) + 3 * ticks["n"]
            return self.clock.t
        self.clock.t = tehran(6, 59, second=50)
        with mock.patch.object(agent, "_now", moving_clock):
            j, site = self.job(window="02:00-07:00")
            meta = agent.h_ollama_pull(j)
        self.assertEqual(len(OL.pulls), 2, "the first stream was cut at 07:00, a second one finished the model")
        self.assertGreater(OL.pulls[1][1] or 10 ** 9, 500, "the second stream went on from the partial bytes, not from zero")
        self.assertIn("gemma3:12b", OL.models)
        self.assertEqual(meta["attempts"], 1, "a closed window is not a failed attempt")
        self.assertTrue(self.slept, "it waited for the next window")
        self.assertTrue(all(self.lock_free_while_waiting), "the line was released while paused")
        self.assertFalse(agent.PULL_LOCK.locked(), "and taken back and released at the end")
        phases = [(d.get("meta") or {}).get("phase") for d in self.progress(site)]
        self.assertIn("window", phases)
        self.assertEqual(phases.index("window") > phases.index("downloading"), True)
        dones = [(d.get("meta") or {}).get("done", 0) for d in self.progress(site) if d.get("meta")]
        self.assertEqual(dones, sorted(dones), "bytes reported never went backwards")

    def test_cancel_while_waiting_for_the_window_ends_the_job_and_frees_the_line(self):
        self.clock.t = tehran(12)
        j, site = self.job(site=PullSite(cancel_after=4), window="02:00-07:00")
        with self.assertRaises(agent.Cancelled):
            agent.h_ollama_pull(j)
        self.assertEqual(OL.pulls, [])
        self.assertFalse(agent.PULL_LOCK.locked())

    def test_the_progress_message_is_persian_and_the_console_line_is_not(self):
        self.clock.t = tehran(12)
        j, site = self.job(window="13:00-14:00")
        agent.h_ollama_pull(j)
        self.assertIn("منتظرِ بازهٔ دانلود — ادامه امروز ۱۳:۰۰", self.progress(site)[1]["message"])
        waits = [m for _l, m in self.lines if "waits for the download window" in m]
        self.assertEqual(len(waits), 1)
        self.assertTrue(all(ord(ch) < 128 for ch in waits[0]))


# ───────────────────────────────────────────── the durable queue: finish / upload / old folders

class SiteDown(Exception):
    pass


class FlakySite:
    def __init__(self, fail=0, error=None):
        self.fail, self.error, self.calls = fail, error, 0

    def post(self, path, data=None, timeout=60):
        self.calls += 1
        if self.calls <= self.fail:
            raise self.error or agent.SiteError("site unreachable (http://x): timed out")
        return {"ok": True}


class RobustnessTests(Base):
    def job(self, site):
        return agent.Job(site, {"uid": "f0000001", "kind": "echo", "payload": {}})

    def test_finish_waits_for_a_short_outage_and_succeeds(self):
        site = FlakySite(fail=4)
        sleeps = []
        self.job(site).finish(True, meta={"x": 1}, sleep=sleeps.append)
        self.assertEqual(site.calls, 5)
        self.assertEqual(sleeps, [2.0, 4.0, 8.0, 16.0], "growing waits")

    def test_finish_gives_up_after_about_five_minutes(self):
        site = FlakySite(fail=10 ** 6)
        sleeps = []
        with self.assertRaises(agent.SiteError):
            self.job(site).finish(True, sleep=sleeps.append)
        self.assertEqual(sum(sleeps), 300.0)
        self.assertLessEqual(max(sleeps), 30.0)
        self.assertEqual(site.calls, len(sleeps) + 1)

    def test_a_short_patience_is_honoured(self):
        site = FlakySite(fail=10 ** 6)
        sleeps = []
        with self.assertRaises(agent.SiteError):
            self.job(site).finish(False, "boom", patience_s=10, sleep=sleeps.append)
        self.assertEqual(sum(sleeps), 10.0)

    def test_a_job_the_site_gave_away_is_not_retried(self):
        site = FlakySite(fail=5, error=agent.JobLost("403"))
        sleeps = []
        with self.assertRaises(agent.JobLost):
            self.job(site).finish(True, sleep=sleeps.append)
        self.assertEqual((site.calls, sleeps), (1, []))

    def test_a_refusal_or_a_rejected_token_is_not_retried_but_a_5xx_is(self):
        for error, retried in ((agent.SiteError("POST /x -> HTTP 400 bad"), False),
                               (agent.SiteError("site rejected the node token (HTTP 401)."), False),
                               (agent.SiteError("POST /x -> HTTP 503 busy"), True)):
            site = FlakySite(fail=1, error=error)
            sleeps = []
            try:
                self.job(site).finish(True, sleep=sleeps.append)
            except agent.SiteError:
                pass
            self.assertEqual(bool(sleeps), retried, str(error))

    def test_upload_is_patient_with_growing_waits(self):
        s = agent.Site("http://x", "tok")
        attempts = []

        def req(method, path, data=None, headers=None, timeout=60, raw=False):
            attempts.append(path)
            if len(attempts) < 8:
                raise agent.SiteError("site unreachable (http://x): reset")
            return {"ok": True}
        s._req = req
        sleeps = []
        with mock.patch.object(agent, "warn", lambda m: None):
            self.assertEqual(s.upload("/up/", {"f": ("a.txt", b"x")}, sleep=sleeps.append), {"ok": True})
        self.assertEqual(len(attempts), 8)
        self.assertEqual(sleeps, [5, 10, 20, 40, 60, 60, 60])

    def test_upload_gives_up_after_eight_tries_and_a_rejection_at_once(self):
        s = agent.Site("http://x", "tok")
        s._req = mock.Mock(side_effect=agent.SiteError("site unreachable (http://x): reset"))
        sleeps = []
        with mock.patch.object(agent, "warn", lambda m: None):
            with self.assertRaises(agent.SiteError):
                s.upload("/up/", {"f": ("a.txt", b"x")}, sleep=sleeps.append)
        self.assertEqual(s._req.call_count, 8)
        self.assertEqual(len(sleeps), 7)
        s._req = mock.Mock(side_effect=agent.SiteError("POST /up/ -> HTTP 413 too large"))
        with self.assertRaises(agent.SiteError):
            s.upload("/up/", {"f": ("a.txt", b"x")}, sleep=sleeps.append)
        self.assertEqual(s._req.call_count, 1)
        s._req = mock.Mock(side_effect=agent.JobLost("403"))
        with self.assertRaises(agent.JobLost):
            s.upload("/up/", {"f": ("a.txt", b"x")}, sleep=sleeps.append)
        self.assertEqual(s._req.call_count, 1)

    def test_the_sweep_removes_only_old_job_folders(self):
        work = agent.WORK
        os.makedirs(work)
        now = time.time()
        old_uid, new_uid, busy_uid = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
        for uid in (old_uid, new_uid, busy_uid):
            os.makedirs(os.path.join(work, uid, "outputs"))
            open(os.path.join(work, uid, "outputs", "a.bin"), "wb").write(b"x")
        os.makedirs(os.path.join(work, "edit-cache"))                       # the editors' own folder: not a job uid
        open(os.path.join(work, "kit-app-voice.zip"), "wb").write(b"x")     # a file
        open(os.path.join(work, "44444444-4444-4444-8444-444444444444"), "wb").write(b"x")   # a FILE named like a uid
        for rel in (old_uid, old_uid + "/outputs", old_uid + "/outputs/a.bin", "edit-cache"):
            os.utime(os.path.join(work, rel), (now - 3 * DAY, now - 3 * DAY))
        os.utime(os.path.join(work, busy_uid), (now - 3 * DAY, now - 3 * DAY))       # its top folder is old, a file inside is fresh
        self.assertEqual(agent.sweep_work(now=now), 1)
        left = sorted(os.listdir(work))
        self.assertNotIn(old_uid, left)
        self.assertIn(new_uid, left)
        self.assertIn(busy_uid, left, "a job that wrote something recently is kept")
        self.assertIn("edit-cache", left)
        self.assertIn("kit-app-voice.zip", left)
        self.assertEqual(agent.sweep_work(now=now), 0)
        self.assertEqual(agent.sweep_work(root=os.path.join(self.tmp, "nowhere")), 0)
        self.assertEqual(agent.sweep_work(now=now + 5 * DAY), 2, "every job folder is old five days later (files are never touched)")


# ───────────────────────────────────────────── numbers for the report page

class NumbersTests(Base):
    def setUp(self):
        super().setUp()
        agent._GPU.update(at=0.0, util=None, temp=None)
        self.addCleanup(agent._GPU.update, at=0.0, util=None, temp=None)

    def smi(self, text, calls):
        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, text, "")
        return run

    def test_gpu_numbers_and_the_cache(self):
        calls = []
        run, which = self.smi("37, 55\n", calls), lambda name: "/usr/bin/nvidia-smi"
        self.assertEqual(agent.gpu_stats(now=1000.0, run=run, which=which), (37, 55))
        self.assertEqual(agent.gpu_stats(now=1030.0, run=run, which=which), (37, 55))
        self.assertEqual(len(calls), 1, "nvidia-smi is asked at most once a minute")
        self.assertIn("--query-gpu=utilization.gpu,temperature.gpu", calls[0])
        calls2 = []
        self.assertEqual(agent.gpu_stats(now=1061.0, run=self.smi("90, 71\n", calls2), which=which), (90, 71))
        self.assertEqual(len(calls2), 1)

    def test_a_machine_without_nvidia_smi_stays_silent_and_does_not_ask_again(self):
        asked = []
        which = lambda name: asked.append(name) or None
        self.assertEqual(agent.gpu_stats(now=1000.0, which=which), (None, None))
        self.assertEqual(agent.gpu_stats(now=1010.0, which=which), (None, None))
        self.assertEqual(len(asked), 1, "the absence is cached too")

    def test_odd_nvidia_smi_output(self):
        which = lambda name: "nvidia-smi"
        self.assertEqual(agent.gpu_stats(now=1.0, run=self.smi("[N/A], [N/A]\n", []), which=which), (None, None))
        agent._GPU["at"] = 0.0
        self.assertEqual(agent.gpu_stats(now=100.0, run=self.smi("12, [N/A]\n", []), which=which), (12, None))
        agent._GPU["at"] = 0.0

        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 10)
        self.assertEqual(agent.gpu_stats(now=200.0, run=boom, which=which), (None, None))
        agent._GPU["at"] = 0.0
        self.assertEqual(agent.gpu_stats(now=300.0, run=self.smi("", []), which=which), (None, None))

    def test_disk_numbers_are_decimal_gb_of_the_data_drive(self):
        free, total = agent.disk_numbers()
        du = shutil.disk_usage(self.tmp)
        self.assertAlmostEqual(total, round(du.total / 1e9, 1), delta=0.2)
        self.assertLessEqual(free, total)
        with mock.patch.object(agent.shutil, "disk_usage", side_effect=OSError("gone")):
            self.assertEqual(agent.disk_numbers(), (None, None))

    def test_the_heartbeat_carries_them(self):
        with mock.patch.object(agent, "listening", lambda *a, **k: False), mock.patch.object(agent, "gpu_names", lambda: []), \
                mock.patch.object(agent, "gpu_stats", lambda: (41, 63)), \
                mock.patch.object(agent, "disk_numbers", lambda: (123.4, 500.0)), \
                mock.patch.object(agent, "find_comfy_start", lambda: None), \
                mock.patch.object(agent, "ollama_models_on_disk", lambda root=None: []):
            caps = agent.Capabilities("TEST-NODE", 1).probe()
            self.assertEqual((caps["disk_free_gb"], caps["disk_total_gb"], caps["gpu_util_pct"], caps["gpu_temp_c"]),
                             (123.4, 500.0, 41, 63))
            self.assertEqual(caps["agent"], "2.12")
        with mock.patch.object(agent, "listening", lambda *a, **k: False), mock.patch.object(agent, "gpu_names", lambda: []), \
                mock.patch.object(agent, "gpu_stats", lambda: (None, None)), \
                mock.patch.object(agent, "disk_numbers", lambda: (None, None)), \
                mock.patch.object(agent, "ollama_models_on_disk", lambda root=None: []):
            caps = agent.Capabilities("TEST-NODE", 1).probe()
        for key in ("disk_free_gb", "disk_total_gb", "gpu_util_pct", "gpu_temp_c"):
            self.assertNotIn(key, caps, "silently absent when it cannot be read")

    def test_the_models_caps_say_when_a_download_waits(self):
        dm = agent.DownloadManager()
        dm.waiting_info = lambda: {"until": "2026-11-08T22:30:00+00:00", "packages": ["a"], "default": False, "reason": "window"}
        self.assertEqual(dm.caps()["waiting"]["reason"], "window")


if __name__ == "__main__":
    unittest.main()
