"""«آخرین بکاپ» و «آزمون‌های شبانهٔ سایت» در پنل: ops_status.py + GET /api/v1/compute/ops/ (فقط کارکنان)."""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.compute import ops_status

User = get_user_model()


def iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class OpsStatusTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.backups = Path(tmp.name, "backups")
        self.data = Path(tmp.name, "data")
        self.backups.mkdir()
        self.data.mkdir()
        env = mock.patch.dict(os.environ, {"NM_BACKUP_DIR": str(self.backups)})
        env.start()
        self.addCleanup(env.stop)
        ov = override_settings(NM_DATA_DIR=self.data)
        ov.enable()
        self.addCleanup(ov.disable)
        ver = mock.patch.object(ops_status, "current_version", return_value="2.95")      # نسخهٔ گزارش‌های این آزمون‌ها؛ «قرمزِ کهنه» در tests_deferred_e
        ver.start()
        self.addCleanup(ver.stop)

    # ---- بکاپ
    def test_no_backup_yet(self):
        self.assertEqual(ops_status.backup_status(), {"present": False, "state": "missing"})

    def test_good_recent_backup(self):
        (self.backups / "status.json").write_text(json.dumps({"ok": True, "at": iso(5), "size_mb": 12}), encoding="utf-8")
        s = ops_status.backup_status()
        self.assertEqual((s["present"], s["state"]), (True, "ok"))
        self.assertAlmostEqual(s["age_hours"], 5, delta=0.1)
        self.assertEqual(s["size_mb"], 12)

    def test_old_backup_is_stale_and_failed_backup_is_failed(self):
        (self.backups / "status.json").write_text(json.dumps({"ok": True, "at": iso(ops_status.BACKUP_STALE_HOURS + 2)}), encoding="utf-8")
        self.assertEqual(ops_status.backup_status()["state"], "stale")
        (self.backups / "status.json").write_text(json.dumps({"ok": False, "at": iso(1), "errors": ["x"]}), encoding="utf-8")
        self.assertEqual(ops_status.backup_status()["state"], "failed")

    def test_unreadable_files_mean_not_yet_not_a_crash(self):
        (self.backups / "status.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(ops_status.backup_status()["state"], "missing")
        (self.data / "test-report.json").write_text("[1,2]", encoding="utf-8")
        self.assertEqual(ops_status.test_status()["state"], "missing")

    # ---- آزمون‌های شبانه
    def _report(self, red_apps=0, failures=0, errors=0, hours_ago=3):
        (self.data / "test-report.json").write_text(json.dumps({
            "started_at": iso(hours_ago + 1), "finished_at": iso(hours_ago), "version": "2.95",
            "apps": [{"app": "jobs", "ok": not red_apps, "tests": 10, "failures": failures, "errors": errors, "skipped": 0, "seconds": 5,
                      "red": [{"id": "t", "kind": "fail", "message": "m"}] if red_apps else []}],
            "totals": {"apps": 1, "red_apps": red_apps, "tests": 10, "failures": failures, "errors": errors, "skipped": 0},
        }), encoding="utf-8")

    def test_tests_missing_green_red_stale(self):
        self.assertEqual(ops_status.test_status(), {"present": False, "state": "missing", "running": None})
        self._report()
        self.assertEqual(ops_status.test_status()["state"], "green")
        self._report(red_apps=1, failures=1)
        s = ops_status.test_status()
        self.assertEqual(s["state"], "red")
        self.assertEqual(s["apps"][0]["red"][0]["id"], "t")
        self._report(hours_ago=ops_status.TESTS_STALE_HOURS + 1)
        self.assertEqual(ops_status.test_status()["state"], "stale")

    def test_running_marker(self):
        marker = self.data / "test-report.json.running"
        since = iso(1)
        marker.write_text(json.dumps({"app": "customers", "since": since}), encoding="utf-8")
        self.assertEqual(ops_status.test_status()["running"], {"app": "customers", "since": since})
        old = time.time() - (ops_status.RUNNING_STALE_HOURS + 1) * 3600
        os.utime(marker, (old, old))
        self.assertIsNone(ops_status.test_status()["running"], "نشانهٔ بازمانده نادیده گرفته می‌شود")


class OpsApiTests(TestCase):
    URL = "/api/v1/compute/ops/"

    def test_anonymous_and_non_staff_are_refused(self):
        self.assertIn(APIClient().get(self.URL).status_code, (401, 403))
        user = User.objects.create_user("ops-plain", password="x")
        c = APIClient()
        c.force_authenticate(user)
        self.assertEqual(c.get(self.URL).status_code, 403)

    def test_staff_gets_both_blocks(self):
        staff = User.objects.create_user("ops-staff", password="x", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"NM_BACKUP_DIR": tmp}), override_settings(NM_DATA_DIR=Path(tmp)):
            r = c.get(self.URL)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["backup"]["state"], "missing")
        self.assertEqual(body["tests"]["state"], "missing")
