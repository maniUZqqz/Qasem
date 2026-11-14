# -*- coding: utf-8 -*-
"""گزارشِ «آمادگیِ صبحِ مالک» (readiness.py، node_readiness، /api/v1/compute/readiness/) — فقط‌خواندنی و درست."""
import io
import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import readiness
from . import updates as U
from .models import ComputeNode, ComputeSettings

PROC = U.source_dir()


def fake_manifest(**over):
    files = [{"path": rel} for rel, _ in U.source_files()]
    m = {"version": readiness._version_of(PROC), "count": len(files), "zip_size": 14_000_000, "files": files}
    m.update(over)
    return m


class ReadinessTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-readiness-"))
        self.ctx = override_settings(NM_DATA_DIR=self.tmp, IS_TEST=True)
        self.ctx.enable()
        self.names = readiness.mirror_names(PROC)
        self.addCleanup(self.ctx.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def listing(self, drop=(), size_of=None):
        rows = [{"name": n, "size": int((size_of or {}).get(n) or declared or 1)} for n, declared in self.names.items() if n not in drop]
        return mock.patch.object(U, "list_downloads", return_value=rows)

    def test_the_mirror_list_holds_every_file_a_node_feature_downloads_from_the_site(self):
        for name in ("blender-windows.zip", "up3d-blender-user.zip", "kit-ffmpeg.zip", "node-v20.18.0-win-x64.zip", "rvm_mobilenetv3_fp32.onnx",
                     "abagram-wheels-cp311-win_amd64.zip", "abagram-chromium-win64.zip", "multiangle-yolos-tiny.onnx", "u2netp.onnx"):
            self.assertIn(name, self.names, name)
        self.assertEqual(self.names["blender-windows.zip"], 398661046)       # the size declared in requirements.d is carried along

    def test_everything_present_is_ok(self):
        with self.listing():
            row = readiness.mirror_rows(PROC)[0]
        self.assertEqual((row["key"], row["state"]), ("mirror", "ok"), row["detail"])

    def test_a_missing_or_wrong_sized_mirror_file_is_a_failure_that_names_it(self):
        with self.listing(drop=("blender-windows.zip",), size_of={"up3d-blender-user.zip": 5}):
            row = readiness.mirror_rows(PROC)[0]
        self.assertEqual(row["state"], "fail")
        self.assertIn("blender-windows.zip", row["detail"])
        self.assertIn("up3d-blender-user.zip", row["detail"])

    def test_the_package_must_carry_the_installer_and_every_requirements_file(self):
        with mock.patch.object(U, "current_manifest", return_value=fake_manifest()):
            rows = {r["key"]: r for r in readiness.package_rows(PROC)}
        self.assertEqual((rows["package"]["state"], rows["package_files"]["state"]), ("ok", "ok"), rows)
        files = [f for f in fake_manifest()["files"] if f["path"] not in ("bootstrap.py", "requirements.d/blender-3d.json")]
        with mock.patch.object(U, "current_manifest", return_value=fake_manifest(files=files, version="0.0")):
            rows = {r["key"]: r for r in readiness.package_rows(PROC)}
        self.assertEqual(rows["package"]["state"], "fail")                         # the package is not the agent.py in the folder
        self.assertEqual(rows["package_files"]["state"], "fail")
        self.assertIn("bootstrap.py", rows["package_files"]["detail"])
        self.assertIn("requirements.d/blender-3d.json", rows["package_files"]["detail"])

    def test_the_download_window_row_says_the_first_install_ignores_it(self):
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "window", "download_window": "02:00-07:00"})
        row = readiness.download_rows()[0]
        self.assertEqual(row["state"], "info")
        self.assertIn("نصبِ نخستِ", row["detail"])
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "now"})
        self.assertEqual(readiness.download_rows()[0]["state"], "ok")

    def test_a_switched_off_automation_is_a_warning(self):
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_update": False})
        rows = {r["key"]: r for r in readiness.automation_rows()}
        self.assertEqual(rows["auto_update"]["state"], "warn")
        self.assertEqual(rows["auto_selftest"]["state"], "ok")

    def test_the_catalog_row_lists_a_feature_without_its_test(self):
        self.assertEqual(readiness.catalog_rows()[0]["state"], "ok")
        broken = dict(readiness.REQUIRED, **{"ویژگیِ بی‌آزمون": ["no_such_test"]})
        with mock.patch.object(readiness, "REQUIRED", broken):
            row = readiness.catalog_rows()[0]
        self.assertEqual(row["state"], "fail")
        self.assertIn("no_such_test", row["detail"])

    def test_the_report_and_the_command_never_write_anything(self):
        node = ComputeNode.objects.create(name="r-node", last_seen=timezone.now() - timedelta(hours=20),
                                          capabilities={"agent": "2.10", "commands": ["update"], "code": {"id": "a" * 16}})
        before = (ComputeNode.objects.count(), node.capabilities)
        with mock.patch.object(U, "current_manifest", return_value=fake_manifest()), self.listing():
            rep = readiness.report()
            out = io.StringIO()
            call_command("node_readiness", "--node", "r-node", stdout=out)
        self.assertTrue(rep["ok"], [r for r in rep["checks"] if r["state"] == "fail"])
        self.assertIn("READY", out.getvalue())
        self.assertIn("خاموش", out.getvalue())
        node.refresh_from_db()
        self.assertEqual((ComputeNode.objects.count(), node.capabilities), before)

    def test_the_command_exits_with_one_when_something_is_wrong(self):
        with mock.patch.object(U, "current_manifest", return_value=fake_manifest()), self.listing(drop=("kit-ffmpeg.zip",)):
            with self.assertRaises(SystemExit) as cm:
                call_command("node_readiness", "--json", stdout=io.StringIO())
        self.assertEqual(cm.exception.code, 1)

    def test_the_api_is_for_staff_and_returns_the_checks(self):
        with mock.patch.object(U, "current_manifest", return_value=fake_manifest()), self.listing():
            self.assertIn(APIClient().get("/api/v1/compute/readiness/").status_code, (401, 403))
            admin = get_user_model().objects.create_user("ready-admin", password="x", is_staff=True, is_superuser=True)
            client = APIClient()
            client.force_authenticate(admin)
            res = client.get("/api/v1/compute/readiness/")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue({"package", "mirror", "download", "catalog"} <= {c["key"] for c in body["checks"]})
        self.assertIn("ok", body)
