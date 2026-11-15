"""آزمونِ «عملیاتِ سرور» (ممیزیِ ۱۴۰۵/۰۸/۲۳، دستهٔ nm_ops): پوشهٔ موقتِ آزمون‌ها، اسکریپت‌های deploy/nm/ops، لاگ، و ۴۰۴ ِ JSON.

اسکریپت‌های bash فقط روی لینوکس/macOS اجرا می‌شوند (روی ویندوزِ توسعه رد می‌شوند). هیچ‌کدام به دادهٔ زنده دست نمی‌زنند:
همه چیز در پوشه‌های موقتِ خودِ آزمون (TemporaryDirectory) است و با متغیرهای NM_* به اسکریپت‌ها داده می‌شود.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from config import logging_utils, test_runner

OPS = Path(__file__).resolve().parents[3] / "deploy" / "nm" / "ops"
POSIX = sys.platform != "win32" and shutil.which("bash") is not None
needs_bash = unittest.skipUnless(POSIX, "bash لازم است (لینوکس)")


def run_script(name: str, *args: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    full = dict(os.environ)
    full.update(env or {})
    return subprocess.run(["bash", str(OPS / name), *args], capture_output=True, text=True, timeout=timeout, env=full)


def age(path: Path, days: float) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


# ───────────────────────────────────────────────────────── ۱) پوشهٔ موقتِ آزمون‌ها
class TestRunnerTempTests(SimpleTestCase):
    def test_this_run_is_inside_the_run_dir(self):
        """کلِ اجرای جاری (حتی کدِ سطحِ ماژول) در پوشهٔ nm-testrun-* است؛ آخرِ اجرا همه‌اش پاک می‌شود."""
        self.assertEqual(settings.TEST_RUNNER, "config.test_runner.NMTestRunner")
        self.assertIn(test_runner.RUN_PREFIX, tempfile.gettempdir())

    def test_enter_and_leave_restore_everything(self):
        runner = test_runner.NMTestRunner()
        before_dir, before_env = tempfile.tempdir, os.environ.get("TMPDIR")
        run_dir = runner._enter_tmp()
        try:
            self.assertTrue(os.path.isdir(run_dir))
            self.assertEqual(tempfile.gettempdir(), run_dir)
            self.assertEqual(os.environ["TMPDIR"], run_dir)
            leaked = tempfile.mkdtemp(prefix="nm-leak-test-")  # همان کاری که ۶۰ ماژول در import می‌کردند
            self.assertTrue(leaked.startswith(run_dir))
            Path(leaked, "big.bin").write_bytes(b"x" * 1000)
        finally:
            runner._leave_tmp()
        self.assertFalse(os.path.exists(run_dir), "پوشهٔ اجرا باید پاک شده باشد")
        self.assertEqual(tempfile.tempdir, before_dir)
        self.assertEqual(os.environ.get("TMPDIR"), before_env)

    def test_keep_flag_keeps_the_folder_for_debugging(self):
        runner = test_runner.NMTestRunner()
        os.environ["NM_KEEP_TEST_TMP"] = "1"
        try:
            run_dir = runner._enter_tmp()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                runner._leave_tmp()
            self.assertIn(run_dir, out.getvalue())
            self.assertTrue(os.path.isdir(run_dir))
        finally:
            os.environ.pop("NM_KEEP_TEST_TMP", None)
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_the_settings_data_root_is_removed_with_the_run(self):
        runner = test_runner.NMTestRunner()
        run_dir = runner._enter_tmp()
        root = Path(os.path.dirname(run_dir)) / f"{test_runner.RUN_PREFIX}{os.getpid()}-root"
        created = not root.exists()
        root.mkdir(exist_ok=True)
        Path(root, "data").mkdir(exist_ok=True)
        try:
            runner._leave_tmp()
            self.assertFalse(root.exists(), "ریشهٔ دادهٔ آزمون (NM_DATA_DIR پیش‌فرض) باید با پایانِ اجرا پاک شود")
        finally:
            if root.exists() and created:
                shutil.rmtree(root, ignore_errors=True)

    def test_dead_runs_are_swept_but_live_ones_are_not(self):
        with tempfile.TemporaryDirectory() as base:
            dead = Path(base, f"{test_runner.RUN_PREFIX}999999999-abc")
            live = Path(base, f"{test_runner.RUN_PREFIX}{os.getpid()}-abc")
            other = Path(base, "nm-something-else")
            for d in (dead, live, other):
                d.mkdir()
                Path(d, "f").write_text("x")
            Path(dead, "ro.txt").write_text("x")
            os.chmod(Path(dead, "ro.txt"), 0o444)
            self.assertEqual(test_runner.sweep_stale(base), 1)
            self.assertFalse(dead.exists())
            self.assertTrue(live.exists())
            self.assertTrue(other.exists(), "فقط پوشه‌های nm-testrun-<pid> را جارو می‌کند")


# ───────────────────────────────────────────────────────── ۲) nm-tmp-sweep
@needs_bash
class TmpSweepTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.log = self.base.parent / f"sweep-{os.getpid()}.log"
        self.addCleanup(lambda: self.log.unlink(missing_ok=True))
        self.old = ["nm-test-data-a", "nm-compute-test-b", "acestep-fake-c", "pip-unpack-d"]
        for name in self.old:
            d = self.base / name
            d.mkdir()
            (d / "x.bin").write_bytes(b"x" * 2048)
            age(d, 3)
        self.keep_young = self.base / "nm-young"
        self.keep_young.mkdir()
        self.keep_other = []
        for name in ("chromium", "pytest-of-root", "nm_underscore", "cheghar-bk-1", "lucide-m2"):
            d = self.base / name
            d.mkdir()
            age(d, 30)
            self.keep_other.append(d)
        self.env = {"NM_SWEEP_DIR": str(self.base), "NM_SWEEP_LOG": str(self.log)}

    def test_dry_run_removes_nothing_and_counts(self):
        r = run_script("nm-tmp-sweep", "--dry-run", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4 entries", r.stdout)
        for name in self.old:
            self.assertTrue((self.base / name).exists())

    def test_only_old_nm_acestep_pip_entries_are_removed(self):
        r = run_script("nm-tmp-sweep", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed 4 entries", r.stdout)
        for name in self.old:
            self.assertFalse((self.base / name).exists(), name)
        self.assertTrue(self.keep_young.exists(), "کمتر از یک روز: نمی‌ماند پاک شود")
        for d in self.keep_other:
            self.assertTrue(d.exists(), f"{d.name} مالِ ما نیست و نباید پاک شود")
        self.assertIn("removed 4 entries", self.log.read_text(encoding="utf-8"))

    def test_refuses_dangerous_directories(self):
        for bad in ("/", "/root", "/home", "/usr", "/var", "/etc"):
            r = run_script("nm-tmp-sweep", "--dry-run", env={"NM_SWEEP_DIR": bad, "NM_SWEEP_LOG": str(self.log)})
            self.assertEqual(r.returncode, 2, bad)


# ───────────────────────────────────────────────────────── ۳) nm-watchdog
class _Handler(BaseHTTPRequestHandler):
    code = 200

    def do_GET(self):  # noqa: N802
        self.send_response(type(self).code)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):  # silent
        pass


@needs_bash
class WatchdogTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.log, self.state = d / "wd.log", d / "wd.fails"
        self.env = {"NM_WD_LOG": str(self.log), "NM_WD_STATE": str(self.state), "NM_WD_DRY": "1", "NM_WD_DEPLOY_LOCK": str(d / "no-such.lock")}

    def _serve(self, code: int):
        _Handler.code = code
        srv = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        return f"http://127.0.0.1:{srv.server_address[1]}/healthz"

    def test_restarts_only_after_three_failures(self):
        env = {**self.env, "NM_WD_URL": "http://127.0.0.1:9/healthz"}  # پورتِ بسته
        for n in (1, 2):
            run_script("nm-watchdog", env=env)
            self.assertEqual(self.state.read_text().strip(), str(n))
            self.assertNotIn("DRY: restart", self.log.read_text(encoding="utf-8"))
        run_script("nm-watchdog", env=env)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("شکستِ 3 از 3", text)
        self.assertIn("DRY: restart nm-web", text)
        self.assertFalse(self.state.exists(), "پس از ری‌استارت شمارنده صفر می‌شود")

    def test_a_healthy_answer_resets_the_counter(self):
        self.state.write_text("2")
        run_script("nm-watchdog", env={**self.env, "NM_WD_URL": self._serve(200)})
        self.assertFalse(self.state.exists())
        self.assertIn("سالم شد", self.log.read_text(encoding="utf-8"))

    def test_a_429_means_alive_not_failed(self):
        """«Too many requests» proves the web server answers; counting it would restart a healthy site."""
        self.state.write_text("2")
        run_script("nm-watchdog", env={**self.env, "NM_WD_URL": self._serve(429)})
        self.assertFalse(self.state.exists())
        self.assertNotIn("DRY: restart", self.log.read_text(encoding="utf-8"))

    def test_a_500_counts_as_a_failure(self):
        run_script("nm-watchdog", env={**self.env, "NM_WD_URL": self._serve(500)})
        self.assertEqual(self.state.read_text().strip(), "1")

    def test_deploy_lock_held_raises_the_limit_to_six(self):
        lock = Path(self.tmp.name, "deploy.lock")
        lock.write_text("")
        holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
        self.addCleanup(holder.kill)
        time.sleep(0.5)
        env = {**self.env, "NM_WD_URL": "http://127.0.0.1:9/healthz", "NM_WD_DEPLOY_LOCK": str(lock)}
        for _ in range(3):
            run_script("nm-watchdog", env=env)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("3 از 6", text)
        self.assertNotIn("DRY: restart", text)


# ───────────────────────────────────────────────────────── ۴) nm-backup
@needs_bash
class BackupTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.root, self.dest = d / "root", d / "backups"
        self.data, self.media = self.root / "data", self.root / "backend" / "media"
        (self.root / "backend").mkdir(parents=True)
        (self.root / "backend" / ".env").write_text("SECRET=x\n")
        for p in (self.data / "audio_library" / "store_1", self.data / "studio-workspaces" / "shop", self.media / "generated", self.media / "voice_previews"):
            p.mkdir(parents=True)
        (self.data / "audio_library" / "store_1" / "a.wav").write_bytes(b"RIFF" + b"0" * 100)
        (self.media / "generated" / "v.mp4").write_bytes(b"v" * 500)
        (self.media / "voice_previews" / "cache.mp3").write_bytes(b"c" * 500)
        self._db(self.data / "db.sqlite3", rows=5)
        self._db(self.data / "studio.sqlite3", rows=2)
        self._db(self.data / "studio-workspaces" / "shop" / "db.sqlite3", rows=1)
        self.env = {
            "NM_ROOT": str(self.root), "NM_DATA_DIR": str(self.data), "NM_MEDIA_DIR": str(self.media), "NM_BACKUP_DIR": str(self.dest),
            "NM_BACKUP_LOG": str(d / "backup.log"), "NM_BACKUP_LOCK": str(d / "backup.lock"), "NM_BACKUP_MIN_FREE_MB": "1",
        }

    @staticmethod
    def _db(path: Path, rows: int):
        con = sqlite3.connect(path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE django_migrations (id integer primary key, app text)")
        con.execute("CREATE TABLE t (id integer primary key, v text)")
        con.executemany("INSERT INTO django_migrations(app) VALUES (?)", [("a",)] * rows)
        con.executemany("INSERT INTO t(v) VALUES (?)", [("x",)] * rows)
        con.commit()
        con.close()

    def _latest(self) -> Path:
        return sorted((self.dest / "daily").iterdir())[-1]

    def test_backup_copies_databases_data_and_config_and_proves_restore(self):
        r = run_script("nm-backup", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = self._latest()
        for name in ("db.sqlite3", "studio.sqlite3", "studio-workspaces__shop__db.sqlite3", "data.tar.gz", "config.tar.gz", "manifest.json"):
            self.assertTrue((b / name).is_file(), name)
        copy = sqlite3.connect(b / "db.sqlite3")
        self.assertEqual(copy.execute("SELECT count(*) FROM t").fetchone()[0], 5)
        self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        copy.close()
        manifest = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["ok"])
        self.assertEqual(len(manifest["databases"]), 3)
        status = json.loads((self.dest / "status.json").read_text(encoding="utf-8"))
        self.assertTrue(status["ok"])
        self.assertTrue(status["restore_test_ok"])
        self.assertEqual(status["daily_kept"], 1)
        self.assertIn("offsite", status)
        self.assertTrue(status["at"].endswith("Z"))
        tar = subprocess.run(["tar", "-tzf", str(b / "data.tar.gz")], capture_output=True, text=True).stdout
        self.assertIn("audio_library/store_1/a.wav", tar)
        self.assertNotIn("sqlite3", tar, "دیتابیس‌ها با .backup می‌آیند، نه با tar")
        self.assertEqual(oct((self.dest).stat().st_mode & 0o777), "0o700")

    def test_verify_detects_a_corrupt_copy(self):
        run_script("nm-backup", env=self.env)
        ok = run_script("nm-backup", "--verify", env=self.env)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        victim = self._latest() / "db.sqlite3"
        victim.write_bytes(victim.read_bytes()[:2048] + b"\x00" * 4096)  # خراب
        bad = run_script("nm-backup", "--verify", env=self.env)
        self.assertNotEqual(bad.returncode, 0)

    def test_rotation_keeps_seven_daily_and_four_weekly(self):
        for sub, n in (("daily", 9), ("weekly", 6), ("media", 6)):
            for i in range(n):
                (self.dest / sub / f"2020010{i}-0000").mkdir(parents=True)
        self.env["NM_BACKUP_FORCE_WEEKLY"] = "1"
        r = run_script("nm-backup", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(list((self.dest / "daily").iterdir())), 7)
        self.assertEqual(len(list((self.dest / "weekly").iterdir())), 4)
        self.assertLessEqual(len(list((self.dest / "media").iterdir())), 4)
        # نسخهٔ تازه جزءِ نگه‌داشته‌هاست
        self.assertTrue((self._latest() / "db.sqlite3").is_file())

    @unittest.skipUnless(shutil.which("rsync"), "rsync لازم است")
    def test_weekly_media_snapshot_skips_caches_and_hardlinks_unchanged_files(self):
        self.env["NM_BACKUP_FORCE_WEEKLY"] = "1"
        self.assertEqual(run_script("nm-backup", env=self.env).returncode, 0)
        snaps = sorted((self.dest / "media").iterdir())
        self.assertEqual(len(snaps), 1)
        self.assertTrue((snaps[0] / "generated" / "v.mp4").is_file())
        self.assertFalse((snaps[0] / "voice_previews").exists(), "کش در بکاپ نمی‌رود")
        # بکاپِ دوم همان روز: فایلِ بی‌تغییر hard-link می‌شود (فضای اضافه نمی‌گیرد)
        (self.dest / "media" / snaps[0].name).rename(self.dest / "media" / "20200101")
        self.assertEqual(run_script("nm-backup", env=self.env).returncode, 0)
        new = sorted(p for p in (self.dest / "media").iterdir() if p.name != "20200101")[0]
        self.assertEqual((new / "generated" / "v.mp4").stat().st_ino, (self.dest / "media" / "20200101" / "generated" / "v.mp4").stat().st_ino)

    def test_a_missing_database_makes_the_status_a_failure_but_never_crashes(self):
        shutil.rmtree(self.data / "studio-workspaces")
        (self.data / "db.sqlite3").unlink()
        r = run_script("nm-backup", env=self.env)
        self.assertNotEqual(r.returncode, 0)
        status = json.loads((self.dest / "status.json").read_text(encoding="utf-8"))
        self.assertFalse(status["ok"])
        self.assertTrue(status["errors"])

    def test_low_disk_skips_media_but_keeps_the_database_backup(self):
        self.env["NM_BACKUP_FORCE_WEEKLY"] = "1"
        self.env["NM_BACKUP_MIN_FREE_MB"] = "999999999"
        self.assertEqual(run_script("nm-backup", env=self.env).returncode, 0)
        status = json.loads((self.dest / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["media"], "skipped-low-disk")
        self.assertTrue((self._latest() / "db.sqlite3").is_file())


# ───────────────────────────────────────────────────────── ۵) nm-nightly-tests (با «پایتونِ» ساختگی)
@needs_bash
class NightlyTestsScript(SimpleTestCase):
    FAKE = """#!/bin/bash
# پایتونِ ساختگی: وقتی «manage.py test <label>» صدا زده شود خروجیِ unittest را چاپ می‌کند.
if [ "$1" = "-X" ]; then
  label="$5"
  case "$label" in
    apps.good) printf 'Creating test database\\n..s\\n----------------------------------------------------------------------\\nRan 3 tests in 0.010s\\n\\nOK (skipped=1)\\n'; exit 0;;
    apps.red) printf '.F.E\\n======================================================================\\nFAIL: test_a (apps.red.tests.A.test_a)\\n----------------------------------------------------------------------\\nTraceback (most recent call last):\\n  File "x.py", line 1\\nAssertionError: 1 != 2\\n\\n======================================================================\\nERROR: test_b (apps.red.tests.A.test_b)\\n----------------------------------------------------------------------\\nTraceback (most recent call last):\\nOperationalError: boom\\n\\n----------------------------------------------------------------------\\nRan 4 tests in 0.020s\\n\\nFAILED (failures=1, errors=1)\\n'; exit 1;;
    apps.crash) printf 'Traceback (most recent call last):\\nImportError: nope\\n'; exit 1;;
  esac
fi
exec python3 "$@"
"""

    def test_per_app_report_with_red_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "backend").mkdir()
            fake = d / "fakepy"
            fake.write_text(self.FAKE)
            fake.chmod(0o755)
            out = d / "report.json"
            env = {
                "NM_ROOT": str(d), "NM_TEST_PYTHON": str(fake), "NM_TEST_REPORT": str(out), "NM_TEST_LOGDIR": str(d / "logs"),
                "NM_HEAVY_LOCK": str(d / "heavy.lock"), "NM_NIGHTLY_LOCK": str(d / "n.lock"), "NM_NIGHTLY_APPS": "good red crash", "NM_NIGHTLY_SKIP": "",
            }
            r = run_script("nm-nightly-tests", env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rep = json.loads(out.read_text(encoding="utf-8"))
            by = {a["app"]: a for a in rep["apps"]}
            self.assertTrue(by["good"]["ok"])
            self.assertEqual((by["good"]["tests"], by["good"]["skipped"]), (3, 1))
            self.assertFalse(by["red"]["ok"])
            self.assertEqual((by["red"]["tests"], by["red"]["failures"], by["red"]["errors"]), (4, 1, 1))
            self.assertEqual([x["kind"] for x in by["red"]["red"]], ["fail", "error"])
            self.assertEqual(by["red"]["red"][0]["id"], "test_a (apps.red.tests.A.test_a)")
            self.assertEqual(by["red"]["red"][0]["message"], "AssertionError: 1 != 2")
            self.assertEqual(by["red"]["red"][1]["message"], "OperationalError: boom")
            self.assertTrue(by["crash"]["crashed"])
            self.assertIn("ImportError: nope", by["crash"]["tail"][-1])
            self.assertEqual(rep["totals"]["apps"], 3)
            self.assertEqual(rep["totals"]["red_apps"], 2)
            self.assertEqual(rep["totals"]["tests"], 7)
            self.assertFalse((d / "report.json.running").exists(), "نشانهٔ «در حالِ اجرا» باید پاک شود")

    def test_a_busy_heavy_lock_skips_the_app_and_is_not_red(self):
        """قفلِ سنگینِ سرور شلوغ است (۲۵ کارِ دیگر در صف): اپ «رد شد» می‌خورد، نه «قرمز/نیمه‌کاره»."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "backend").mkdir()
            fake = d / "fakepy"
            fake.write_text(self.FAKE)
            fake.chmod(0o755)
            lock = d / "heavy.lock"
            lock.write_text("")
            holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
            self.addCleanup(holder.kill)
            time.sleep(0.5)
            out = d / "report.json"
            env = {"NM_ROOT": str(d), "NM_TEST_PYTHON": str(fake), "NM_TEST_REPORT": str(out), "NM_TEST_LOGDIR": str(d / "logs"),
                   "NM_HEAVY_LOCK": str(lock), "NM_HEAVY_WAIT": "1", "NM_NIGHTLY_LOCK": str(d / "n.lock"), "NM_NIGHTLY_APPS": "good", "NM_NIGHTLY_SKIP": ""}
            self.assertEqual(run_script("nm-nightly-tests", env=env).returncode, 0)
            rep = json.loads(out.read_text(encoding="utf-8"))
            app = rep["apps"][0]
            self.assertTrue(app["lock_timeout"])
            self.assertTrue(app["ok"])
            self.assertFalse(app["crashed"])
            self.assertEqual(app["tests"], 0)
            self.assertEqual(rep["totals"]["lock_skipped"], 1)
            self.assertEqual(rep["totals"]["red_apps"], 0)

    def test_skip_list_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "backend").mkdir()
            fake = d / "fakepy"
            fake.write_text(self.FAKE)
            fake.chmod(0o755)
            out = d / "report.json"
            env = {"NM_ROOT": str(d), "NM_TEST_PYTHON": str(fake), "NM_TEST_REPORT": str(out), "NM_TEST_LOGDIR": str(d / "logs"),
                   "NM_HEAVY_LOCK": str(d / "heavy.lock"), "NM_NIGHTLY_LOCK": str(d / "n.lock"), "NM_NIGHTLY_APPS": "good red", "NM_NIGHTLY_SKIP": "red"}
            self.assertEqual(run_script("nm-nightly-tests", env=env).returncode, 0)
            self.assertEqual([a["app"] for a in json.loads(out.read_text(encoding="utf-8"))["apps"]], ["good"])


# ───────────────────────────────────────────────────────── ۶) logrotate، reload، unitها
class DeployFilesTests(SimpleTestCase):
    def test_logrotate_config_is_valid_and_covers_every_nm_log(self):
        conf = (OPS / "nm-logrotate.conf").read_text(encoding="utf-8")
        for needle in ("celery.log", "celery-node.log", "beat.log", "web-access.log", "web-error.log", "nm-8040.log", "nm-8040.error.log",
                       "daily", "rotate 14", "compress", "copytruncate"):
            self.assertIn(needle, conf)
        rules = "\n".join(line for line in conf.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotIn("django-errors.log", rules, "django-errors.log را خودِ RotatingFileHandler می‌چرخاند")
        self.assertNotIn("cheghar", conf.lower(), "لاگ‌های چغر دست نمی‌خورد")
        if shutil.which("logrotate"):
            with tempfile.TemporaryDirectory() as tmp:
                r = subprocess.run(["logrotate", "-d", "-s", str(Path(tmp, "state")), str(OPS / "nm-logrotate.conf")], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("error:", (r.stdout + r.stderr).lower())

    def test_systemd_units_have_a_graceful_reload_and_quiet_beat(self):
        root = OPS.parents[2]
        for rel in ("deploy/nm/nm-web.service",):
            text = (root / rel).read_text(encoding="utf-8")
            self.assertIn("ExecReload=/bin/kill -s HUP $MAINPID", text)
        beat = (root / "deploy/nm/nm-celery-beat.service").read_text(encoding="utf-8")
        self.assertIn("--loglevel=WARNING", beat)

    def test_cron_runs_every_job_as_root_and_nightly_tests_use_the_heavy_lock_via_the_script(self):
        cron = (OPS / "nm-ops.cron").read_text(encoding="utf-8")
        for needle in ("nm-watchdog", "nm-backup", "nm-tmp-sweep", "nm-nightly-tests"):
            self.assertIn(needle, cron)
        self.assertIn("*/2 * * * *", cron)
        self.assertIn("50 3 * * *", cron)
        self.assertNotIn("cheghar", cron.lower())
        for line in cron.splitlines():
            if line and not line.startswith(("#", "SHELL", "PATH")):
                self.assertIn(" root ", line)

    def test_every_ops_script_has_a_shebang_and_parses(self):
        for name in ("nm-tmp-sweep", "nm-reload", "nm-backup", "nm-watchdog", "nm-nightly-tests", "install-ops.sh"):
            path = OPS / name
            self.assertTrue(path.is_file(), name)
            self.assertTrue(path.read_text(encoding="utf-8").startswith("#!/bin/bash"), name)
            self.assertNotIn("\r", path.read_text(encoding="utf-8"), f"{name}: CRLF")
            if POSIX:
                r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_autopush_excludes_backups_and_previous_builds(self):
        text = (OPS.parent / "git-autopush.sh").read_text(encoding="utf-8")
        self.assertIn("--exclude='*.bak*'", text)
        self.assertIn("--exclude='frontend/dist.prev*'", text)
        gi = (OPS.parents[2] / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*.bak*", gi)


@needs_bash
class InstallOpsTests(SimpleTestCase):
    """install-ops.sh روی پوشه‌های موقت (هرگز روی /etc یا /usr/local ِ واقعی)."""

    def test_installs_scripts_cron_logrotate_and_patches_units_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for sub in ("bin", "systemd", "logrotate.d", "cron.d"):
                (d / sub).mkdir()
            (d / "systemd" / "nm-web.service").write_text("[Service]\nWorkingDirectory=/x\nExecStart=/venv/bin/gunicorn app\nRestart=always\n")
            (d / "systemd" / "nm-celery-beat.service").write_text("[Service]\nExecStart=/venv/bin/celery beat --loglevel=INFO --logfile=/x.log\n")
            env = {"NM_OPS_BIN": str(d / "bin"), "NM_OPS_SYSTEMD": str(d / "systemd"), "NM_OPS_LOGROTATE_D": str(d / "logrotate.d"),
                   "NM_OPS_CRON_D": str(d / "cron.d"), "NM_OPS_NO_SYSTEMCTL": "1"}
            r = run_script("install-ops.sh", env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for name in ("nm-tmp-sweep", "nm-reload", "nm-backup", "nm-watchdog", "nm-nightly-tests"):
                p = d / "bin" / name
                self.assertTrue(p.is_file(), name)
                self.assertTrue(os.access(p, os.X_OK), name)
            self.assertTrue((d / "cron.d" / "nm-ops").is_file())
            self.assertTrue((d / "logrotate.d" / "nm").is_file())
            web = (d / "systemd" / "nm-web.service").read_text()
            self.assertEqual(web.count("ExecReload=/bin/kill -s HUP $MAINPID"), 1)
            self.assertLess(web.index("ExecStart="), web.index("ExecReload="))
            self.assertIn("Restart=always", web)
            self.assertIn("--loglevel=WARNING", (d / "systemd" / "nm-celery-beat.service").read_text())
            again = run_script("install-ops.sh", env=env)
            self.assertEqual(again.returncode, 0)
            self.assertIn("از قبل به‌روز", again.stdout)
            self.assertEqual((d / "systemd" / "nm-web.service").read_text().count("ExecReload="), 1)

    def test_check_mode_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for sub in ("bin", "systemd", "logrotate.d", "cron.d"):
                (d / sub).mkdir()
            env = {"NM_OPS_BIN": str(d / "bin"), "NM_OPS_SYSTEMD": str(d / "systemd"), "NM_OPS_LOGROTATE_D": str(d / "logrotate.d"),
                   "NM_OPS_CRON_D": str(d / "cron.d"), "NM_OPS_NO_SYSTEMCTL": "1"}
            r = run_script("install-ops.sh", "--check", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(list((d / "bin").iterdir()), [])
            self.assertEqual(list((d / "cron.d").iterdir()), [])


# ───────────────────────────────────────────────────────── ۷) لاگ
class LoggingUtilsTests(SimpleTestCase):
    def _record(self, name="x", level=logging.INFO, args=None, **extra):
        rec = logging.LogRecord(name, level, __file__, 1, "Task %s[%s] received", args or ("apps.compute.tasks.maintenance", "abc"), None)
        for k, v in extra.items():
            setattr(rec, k, v)
        return rec

    def test_formatter_is_utc_with_z(self):
        fmt = logging_utils.UtcFormatter("{asctime} {message}", style="{")
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", None, None)
        rec.created = 0
        self.assertEqual(fmt.format(rec), "1970-01-01 00:00:00Z hi")

    def test_request_info_is_added(self):
        class U:
            is_authenticated = True
            pk = 42

        class R:
            path, method, user = "/api/v1/x/", "POST", U()

        rec = self._record(request=R())
        self.assertTrue(logging_utils.RequestInfoFilter().filter(rec))
        self.assertEqual((rec.path, rec.method, rec.user_id), ("/api/v1/x/", "POST", "42"))
        plain = self._record()
        logging_utils.RequestInfoFilter().filter(plain)
        self.assertEqual((plain.path, plain.user_id), ("-", "-"))

    def test_request_info_never_raises(self):
        class R:
            path, method = "/p", "GET"

            @property
            def user(self):
                raise RuntimeError("db down")

        rec = self._record(request=R())
        self.assertTrue(logging_utils.RequestInfoFilter().filter(rec))
        self.assertEqual(rec.user_id, "-")

    def test_periodic_task_chatter_is_dropped_but_warnings_and_real_jobs_stay(self):
        flt = logging_utils.QuietPeriodicTasksFilter(names={"apps.compute.tasks.maintenance"})
        self.assertFalse(flt.filter(self._record()), "maintenance received")
        succeeded = logging.LogRecord("celery.app.trace", logging.INFO, __file__, 1, "Task %(name)s[%(id)s] succeeded in %(runtime)ss: %(return_value)s",
                                      {"name": "apps.compute.tasks.maintenance", "id": "i", "runtime": 0.1, "return_value": None}, None)
        self.assertFalse(flt.filter(succeeded))
        poll = self._record(args=("apps.thumbs.tasks.poll_thumb_task", "i"))
        self.assertFalse(flt.filter(poll), "poll_* ها خودشان را هر چند ثانیه صف می‌کنند")
        real = self._record(args=("apps.content.tasks.generate_video_task", "i"))
        self.assertTrue(flt.filter(real))
        warn = self._record(level=logging.WARNING)
        self.assertTrue(flt.filter(warn), "WARNING هیچ‌وقت حذف نمی‌شود")
        failed = logging.LogRecord("celery.app.trace", logging.ERROR, __file__, 1, "Task %(name)s[%(id)s] raised", {"name": "apps.compute.tasks.maintenance", "id": "i"}, None)
        self.assertTrue(flt.filter(failed))

    def test_celery_handlers_are_switched_to_utc(self):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)sZ: %(message)s]"))
        logger = logging.getLogger("nm-test-celery-utc")
        logger.handlers = [handler]
        logging_utils.utc_celery_handlers(logger)
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", None, None)
        rec.created = 0
        self.assertEqual(handler.format(rec).split(",")[0], "[1970-01-01 00:00:00")
        logging_utils.utc_celery_handlers(None)  # بی‌لاگر هم نمی‌ترکد

    def test_celery_log_format_carries_the_z_marker(self):
        self.assertIn("%(asctime)sZ", settings.CELERY_WORKER_LOG_FORMAT)
        self.assertIn("%(asctime)sZ", settings.CELERY_WORKER_TASK_LOG_FORMAT)

    def test_noisy_names_come_from_the_beat_schedule(self):
        from datetime import timedelta
        from django.test import override_settings

        class Every:
            def __init__(self, seconds):
                self.run_every = timedelta(seconds=seconds)

        beat = {
            "fast": {"task": "t.fast", "schedule": 60.0},
            "obj": {"task": "t.obj", "schedule": Every(300)},
            "slow": {"task": "t.slow", "schedule": 3600.0},
            "cron": {"task": "t.cron", "schedule": object()},
        }
        with override_settings(CELERY_BEAT_SCHEDULE=beat):
            self.assertEqual(logging_utils.noisy_task_names(), {"t.fast", "t.obj"})

    def test_settings_wire_the_file_handler_and_the_filters(self):
        cfg = settings.LOGGING
        self.assertIn("errors_file", cfg["handlers"])
        handler = cfg["handlers"]["errors_file"]
        self.assertEqual(handler["level"], "WARNING")
        self.assertTrue(handler["class"].endswith("RotatingFileHandler"))
        self.assertTrue(str(handler["filename"]).endswith("django-errors.log"))
        self.assertIn("errors_file", cfg["root"]["handlers"])
        for name in ("celery.worker.strategy", "celery.app.trace"):
            self.assertIn("quiet_periodic", cfg["loggers"][name]["filters"])
        self.assertEqual(cfg["formatters"]["verbose"]["()"], "config.logging_utils.UtcFormatter")


# ───────────────────────────────────────────────────────── ۸) ۴۰۴ ِ JSON برای API
class ApiNotFoundTests(TestCase):
    def test_unknown_api_path_is_persian_json_whatever_debug_is(self):
        for debug in (True, False):
            with self.settings(DEBUG=debug):
                r = self.client.get("/api/v1/definitely-not-a-route/")
                self.assertEqual(r.status_code, 404)
                self.assertTrue(r["Content-Type"].startswith("application/json"), r["Content-Type"])
                body = r.json()
                self.assertEqual(body["error"]["code"], "not_found")
                self.assertRegex(body["detail"], r"[آ-ی]")
                self.assertLess(len(r.content), 2000, "نه صفحهٔ ۱۱۹ کیلوبایتیِ HTML")

    def test_post_and_other_methods_get_json_not_a_csrf_page(self):
        for method in ("post", "put", "delete", "patch"):
            r = getattr(self.client, method)("/api/v1/no-such-thing/")
            self.assertEqual(r.status_code, 404, method)
            self.assertEqual(r.json()["error"]["code"], "not_found")

    def test_real_routes_still_answer(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertNotEqual(self.client.get("/api/v1/version/").status_code, 404)

    def test_the_catch_all_is_the_last_api_route(self):
        """هر مسیرِ api/ ای که بعد از ۴۰۴ ِ فراگیر بیاید هیچ‌وقت به دست نمی‌رسد؛ این آزمون جلوی آن را می‌گیرد."""
        from config import urls

        patterns = list(urls.urlpatterns)
        idx = next(i for i, p in enumerate(patterns) if str(p.pattern) == "^api/.*$")
        for later in patterns[idx + 1:]:
            self.assertFalse(str(later.pattern).startswith(("api/", "^api/")), f"مسیرِ {later.pattern} بعد از ۴۰۴ ِ فراگیر است و هرگز دیده نمی‌شود")


# ───────────────────────────────────────────────────────── ۹) آزمون‌ها بسته (hermetic) اجرا می‌شوند
class HermeticSettingsTests(SimpleTestCase):
    def test_dotenv_values_do_not_leak_into_tests(self):
        self.assertEqual(settings.UPMARKET_PUBLISHING["PUBLIC_BASE_URL"], "http://localhost:8000")
        self.assertEqual(settings.EMAIL_HOST, "")
        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)
        self.assertEqual(settings.CELERY_MODE_SOURCE, "test")

    def test_ai_cloud_is_never_configured_in_tests(self):
        """کلیدِ Metis در .env هست؛ آزمون‌ها نباید هرگز با آن تماسِ واقعی (و پولی) بگیرند."""
        self.assertFalse(os.getenv("AI_API_KEY"))

    def test_the_broker_is_never_probed_in_tests(self):
        from apps.jobs import services

        self.assertFalse(services.broker_reachable(force=True))
