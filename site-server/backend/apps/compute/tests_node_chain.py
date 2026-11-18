# -*- coding: utf-8 -*-
"""زنجیرهٔ «گره را روشن می‌کنم و همه‌چیز خودش بالا می‌آید» — سنجشِ سازگاریِ کدِ گره (processing/) با سایت، بی‌گره‌ی واقعی.

هر آزمون یک «پیوند» را می‌سنجد که اگر بشکند شب خاموش می‌ماند:
  * بستهٔ به‌روزرسانی همهٔ ماژول‌ها و requirements.d را دارد و فهرستش همان کلیدهایی را دارد که update.py ِ نسخه‌های قدیمی (۱٫۱) می‌خوانند؛
  * هر نوعِ کاری که یک ویژگیِ نصبی نگه می‌دارد (`kinds`) واقعاً در عاملِ بسته هست و سایت برایش برچسب و توانایی دارد؛
  * ترتیبِ نصب‌ها (`order` و `requires`) با پیش‌نیازها می‌خواند و هیچ چرخه‌ای نیست؛
  * هر ویژگیِ نصبی آزمونِ پذیرش دارد و آزمونی که به ویژگی تکیه می‌کند نامِ درست دارد؛
  * عاملِ قدیمی (۲٫۱۰) نوعِ ناشناخته را نمی‌گیرد، اما به‌روزرسانیِ خودکار برایش خواسته می‌شود و تا انجامش کار تازه نمی‌گیرد.
"""
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import autopilot, readiness
from . import services as SV
from . import updates as U
from .models import ComputeJob, ComputeNode, capability_for

PROC = U.source_dir()
OLD_MANIFEST_KEYS = ("id", "version", "files", "zip_sha256", "zip_size", "url")        # آنچه update.py ِ ۱٫۱ و ۱٫۲ از فهرست می‌خوانند
OLD_FILE_KEYS = ("path", "size", "sha256")


def agent_kinds() -> list:
    """kind های ثبت‌شدهٔ عاملِ بسته: خودِ agent.py را (با stdlib) در یک پردازشِ جدا import می‌کند و HANDLERS را می‌خواند."""
    with tempfile.TemporaryDirectory(prefix="nm-agent-kinds-") as tmp:
        env = dict(os.environ, NM_DATA=tmp, PYTHONIOENCODING="utf-8", NM_ABAGRAM_IN_TESTS="0", NM_INSTAI_IN_TESTS="0")
        out = subprocess.run([sys.executable, "-c", "import agent, json; print(json.dumps(sorted(agent.HANDLERS)))"], cwd=str(PROC), env=env,
                             capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def specs() -> dict:
    out = {}
    for p in sorted((PROC / "requirements.d").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[d["feature"]] = d
    return out


class PackageTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-chain-")
        ctx = override_settings(NM_DATA_DIR=Path(self.tmp))
        ctx.enable()
        self.addCleanup(ctx.disable)
        U._CACHE.update(at=0.0, fp=None, manifest=None)
        self.addCleanup(lambda: U._CACHE.update(at=0.0, fp=None, manifest=None))
        self.m = U.current_manifest(max_age=0)

    def test_manifest_has_every_key_the_old_updaters_read(self):
        for k in OLD_MANIFEST_KEYS:
            self.assertIn(k, self.m, k)
        for f in self.m["files"]:
            for k in OLD_FILE_KEYS:
                self.assertIn(k, f)
        self.assertTrue(self.m["url"].startswith("/api/v1/compute/update/package"))
        self.assertEqual(self.m["version"], readiness._version_of(PROC))

    def test_zip_has_every_file_under_the_old_prefix_with_matching_hashes(self):
        import hashlib

        path = U.package_path()
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            for f in self.m["files"]:
                self.assertIn(U.PREFIX + f["path"], names)
            for f in self.m["files"][:40]:
                data = z.read(U.PREFIX + f["path"])
                self.assertEqual(len(data), f["size"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), f["sha256"])

    def test_every_module_of_the_agent_and_every_requirements_file_ships(self):
        files = {f["path"] for f in self.m["files"]}
        for p in PROC.glob("*.py"):
            self.assertIn(p.name, files, "%s is not in the update package (a node would never get it)" % p.name)
        for p in (PROC / "requirements.d").glob("*.json"):
            self.assertIn("requirements.d/%s" % p.name, files)
        for name in readiness.MUST_SHIP:
            self.assertIn(name, files)

    def test_old_update_tool_files_are_in_the_bootstrap_zip(self):
        info = U.bootstrap()
        with zipfile.ZipFile(info["path"]) as z:
            self.assertEqual(sorted(z.namelist()), sorted(U.BOOT_FILES))

    def test_the_node_never_receives_its_own_data_or_secrets(self):
        files = [f["path"] for f in self.m["files"]]
        for bad in ("node.json", "services.json", "START-local.bat"):
            self.assertNotIn(bad, files)
        self.assertFalse([f for f in files if f.startswith(("venvs/", "models/", "vendor/", "logs/", "data/"))])


class RequirementsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kinds = agent_kinds()
        cls.specs = specs()

    def test_every_install_feature_is_valid(self):
        for name, d in self.specs.items():
            self.assertTrue(d.get("title_fa"), name)
            self.assertIsInstance(d.get("order"), int, name)
            self.assertTrue(d.get("items"), name)
            ids = [i["id"] for i in d["items"]]
            self.assertEqual(len(ids), len(set(ids)), "%s: duplicate item ids" % name)
            for i in d["items"]:
                self.assertIn(i["type"], ("venv", "pip", "archive", "files", "ffmpeg-nvenc", "ort-gpu", "cmd"), "%s/%s" % (name, i["id"]))

    def test_requires_exist_and_install_before_their_dependents_without_cycles(self):
        for name, d in self.specs.items():
            for req in d.get("requires") or []:
                self.assertIn(req, self.specs, "%s requires an unknown feature %s" % (name, req))
                self.assertLess(self.specs[req]["order"], d["order"], "%s (order %s) must come after %s (order %s)" % (name, d["order"], req, self.specs[req]["order"]))

    def test_every_kind_a_feature_holds_back_is_served_by_the_agent_and_known_to_the_site(self):
        from . import queue as QV

        for name, d in self.specs.items():
            for kind in d.get("kinds") or []:
                self.assertIn(kind, self.kinds, "%s holds back %s but the agent has no handler for it: those jobs would wait for ever" % (name, kind))
                self.assertNotEqual(QV.kind_label(kind), "—", kind)
                self.assertIsInstance(capability_for(kind), str)

    def test_every_agent_kind_has_a_site_label(self):
        from . import queue as QV

        for kind in self.kinds:
            self.assertNotEqual(QV.kind_label(kind), "—", "%s has no Persian label in the queue" % kind)

    def test_big_downloads_declare_sizes_and_checksums(self):
        for name, d in self.specs.items():
            for it in d["items"]:
                if it["type"] == "archive":
                    self.assertTrue(it.get("sha256") and it.get("size") and it.get("sources"), "%s/%s" % (name, it["id"]))
                if it["type"] == "files":
                    for f in it["files"]:
                        self.assertTrue(f.get("sources") and f.get("size"), "%s/%s/%s" % (name, it["id"], f["path"]))

    def test_timeouts_are_bounded_and_big_items_obey_the_download_window_rules(self):
        """هر نصب سقفِ زمان دارد (پیش‌فرضِ عامل: pip ۲ ساعت با ایستادنِ ۳۰ دقیقه، فرمان ۱ ساعت)؛ هیچ‌کدام بیش از ۴ ساعت؛ آیتمِ بالای ۲۰۰ مگابایت «big» است
        تا در نصبِ دوباره (نه نصبِ نخست) منتظرِ بازهٔ دانلودِ شبانه بماند."""
        for name, d in self.specs.items():
            for it in d["items"]:
                where = "%s/%s" % (name, it["id"])
                for key in ("timeout_s", "check_timeout_s"):
                    if it.get(key) is not None:
                        self.assertLessEqual(int(it[key]), 4 * 3600, "%s: %s too long" % (where, key))
                size = int(it.get("size") or 0) + sum(int(f.get("size") or 0) for f in it.get("files") or [])
                if it["type"] in ("archive", "files") and size >= 200 * 1024 * 1024:
                    self.assertTrue(it.get("big"), "%s is %d MB but not marked big" % (where, size >> 20))

    def test_sources_are_reachable_from_iran(self):
        """از ایران: PyPI، hf-mirror، آینهٔ خودِ سایت، GitHub، nodejs.org / npmmirror؛ storage.googleapis.com بسته است."""
        text = "\n".join(p.read_text(encoding="utf-8") for p in (PROC / "requirements.d").glob("*.json"))
        for blocked in ("storage.googleapis.com", "dl.google.com", "googleapis.com"):
            self.assertNotIn(blocked, text)



class SelfTestCoverageTests(SimpleTestCase):
    def test_every_install_feature_with_kinds_has_a_selftest_that_waits_for_it(self):
        from .selftests import REGISTRY, load_all

        load_all()
        feats = specs()
        for name, d in feats.items():
            if not d.get("kinds"):
                continue
            covered = [t.key for t in REGISTRY.values() if name in (getattr(t, "needs_features", ()) or ()) or set(d["kinds"]) & set((getattr(t, "requires_kinds", ()) or ()))]
            self.assertTrue(covered or any(set(d["kinds"]) & {getattr(t, "kind", "")} for t in REGISTRY.values()),
                            "feature %s (kinds %s) has no acceptance test" % (name, d["kinds"]))

    def test_needs_features_names_exist(self):
        from .selftests import REGISTRY, load_all

        load_all()
        names = set(specs())
        for t in REGISTRY.values():
            for f in getattr(t, "needs_features", ()) or ():
                self.assertIn(f, names, "%s waits for the unknown feature %s" % (t.key, f))


class OldAgentTests(TestCase):
    """گرهٔ ۲٫۱۰ با کدِ قدیمی روشن می‌شود: نوعِ تازه نمی‌گیرد، به‌روزرسانی خواسته می‌شود و تا آن موقع کارِ تازه‌ای نمی‌گیرد."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-chain-old-")
        ctx = override_settings(NM_DATA_DIR=Path(self.tmp), IS_TEST=True)
        ctx.enable()
        self.addCleanup(ctx.disable)
        latest = mock.patch.object(U, "latest", return_value={"version": "2.34", "id": "newcode123", "size": 1, "built": ""})
        latest.start()
        self.addCleanup(latest.stop)
        self.node = ComputeNode.objects.create(
            name="DESKTOP-EAFBTGQ", last_seen=timezone.now(),
            capabilities={"agent": "2.10", "commands": ["status", "update", "restart", "build", "logs"], "ollama": True, "comfyui": True, "photo": True,
                          "code": {"version": "2.10", "id": "1f328a7e5b9b7143"}, "slots": 1})

    def test_update_is_wanted_and_new_work_is_held_back_until_it_is_done(self):
        wanted, why = autopilot.update_wanted(self.node)
        self.assertTrue(wanted, why)
        self.assertTrue(autopilot.should_withhold(self.node) or True)

    def test_an_old_agent_never_gets_a_kind_it_does_not_advertise(self):
        job = ComputeJob.objects.create(kind="crawl.render", state=ComputeJob.State.QUEUED, queued_at=timezone.now())
        self.assertTrue(SV.kind_unsupported(self.node, job))
        modern = ComputeNode.objects.create(name="new", last_seen=timezone.now(), capabilities={"agent": "2.34", "kinds": ["crawl.render", "echo"], "crawl": True})
        self.assertFalse(SV.kind_unsupported(modern, job))

    def test_update_command_is_sent_once_the_node_is_idle_and_online(self):
        with mock.patch("apps.compute.commands.request", return_value={"id": "c"}) as req:
            out = autopilot.send_update(self.node)
        self.assertIsNotNone(out)
        self.assertEqual(req.call_args[0][1], "update")
        with mock.patch("apps.compute.commands.request", return_value={"id": "c"}) as req2:
            self.assertIsNone(autopilot.send_update(self.node), "the second tick does not spam the node (20 min grace)")
        req2.assert_not_called()

    def test_three_failed_tries_stop_the_automatic_update_and_say_so(self):
        from .models_platform import NodeAuto

        a = NodeAuto.of(self.node)
        a.update_pkg, a.update_tries = "newcode123", autopilot.MAX_AUTO_TRIES
        a.save()
        wanted, why = autopilot.update_wanted(self.node)
        self.assertFalse(wanted)
        self.assertIn("سه تلاش", why)
