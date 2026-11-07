# -*- coding: utf-8 -*-
"""آزمونِ نسخه: خواندنِ فایل‌ها، تحمل‌پذیریِ تجزیه‌گر، دو اندپوینتِ عمومی و bump-version.sh.

اجرا:  cd backend && python manage.py test apps.common.tests_versioning
همه SimpleTestCase‌اند: بی‌دیتابیس. اگر اندپوینت به DB دست بزند، همین‌جا می‌ترکد.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from . import versioning

REPO_ROOT = Path(__file__).resolve().parents[3]
BUMP = REPO_ROOT / "deploy" / "nm" / "bump-version.sh"

SAMPLE = """# چه چیزی تازه است

مقدمه که نباید جزءِ هیچ نسخه‌ای شود.

## v2.60 — ۱۴۰۵/۰۸/۱۶

نوشتهٔ کوتاهِ زیرِ تیتر.

- صفِ پردازشِ **ماندگار** برای کارهای سنگین
- گزارشِ سرورها
  که در دو خط نوشته شده
* دانلودِ زمان‌بندی‌شده
1. نشانِ نسخه

## v2.59
- فقط یک خط

## نه نسخه است
- این بولت به هیچ نسخه‌ای نمی‌رسد
"""


class _TempRoot(SimpleTestCase):
    """هر آزمون یک پوشهٔ ریشهٔ موقت دارد که NM_VERSION_DIR به آن اشاره می‌کند."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-ver-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.dict(os.environ, {"NM_VERSION_DIR": str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        versioning.clear_cache()
        self.addCleanup(versioning.clear_cache)

    def write(self, name, text, binary=False):
        p = self.tmp / name
        if binary:
            p.write_bytes(text)
        else:
            p.write_text(text, encoding="utf-8")
        return p


class VersionFileTests(_TempRoot):
    def test_reads_version_and_build(self):
        self.write("VERSION", "2.60\n")
        self.write("build.json", json.dumps({"version": "2.60", "built_at": "2026-11-07T05:30:00Z", "commit": "ABC1234"}))
        b = versioning.read_build()
        self.assertEqual(b, {"version": "2.60", "built_at": "2026-11-07T05:30:00Z", "commit": "abc1234", "name": "NMarketing"})
        self.assertEqual(versioning.read_version(), "2.60")

    def test_missing_files_mean_unknown_not_error(self):
        b = versioning.read_build()
        self.assertEqual(b["version"], "")
        self.assertEqual(b["built_at"], "")
        self.assertEqual(b["name"], "NMarketing")
        self.assertEqual(versioning.read_version(), "")
        self.assertEqual(versioning.read_changelog(), [])

    def test_garbage_version_is_unknown(self):
        for junk in ["", "\n\n", "hello", "2.6", "2", "2.60.1", "<html>", "2.60; rm -rf /", "9999.99"]:
            self.write("VERSION", junk)
            versioning.clear_cache()
            self.assertEqual(versioning.read_version(), "", msg=repr(junk))

    def test_binary_garbage_never_raises(self):
        self.write("VERSION", b"\xff\xfe\x00\x01garbage\x80", binary=True)
        self.write("build.json", b"\x00\x01\x02{{{", binary=True)
        self.write("CHANGELOG-fa.md", b"\xff\xfe\x00## v2.60\n\x80\x81- x", binary=True)
        self.assertEqual(versioning.read_build()["version"], "")
        self.assertIsInstance(versioning.read_changelog(), list)

    def test_bad_build_json_keeps_version(self):
        self.write("VERSION", "2.61\n")
        for junk in ["not json", "[]", "null", '{"built_at": 5, "commit": {"x": 1}}', '{"built_at": "yesterday", "commit": "zzz"}']:
            self.write("build.json", junk)
            versioning.clear_cache()
            b = versioning.read_build()
            self.assertEqual(b["version"], "2.61", msg=junk)
            self.assertEqual(b["commit"], "", msg=junk)
            # تاریخِ نامعتبر ⇒ زمانِ تغییرِ VERSION جایگزین می‌شود
            self.assertRegex(b["built_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", msg=junk)

    def test_stale_build_json_does_not_leak_into_new_version(self):
        self.write("VERSION", "2.70\n")
        self.write("build.json", json.dumps({"version": "2.60", "built_at": "2020-01-01T00:00:00Z", "commit": "deadbee"}))
        b = versioning.read_build()
        self.assertEqual(b["version"], "2.70")
        self.assertEqual(b["commit"], "")
        self.assertNotEqual(b["built_at"], "2020-01-01T00:00:00Z")

    def test_persian_digits_and_v_prefix_in_version(self):
        self.write("VERSION", "v۲.۶۰\n")
        self.assertEqual(versioning.read_version(), "2.60")

    def test_cache_follows_file_changes(self):
        p = self.write("VERSION", "2.60\n")
        self.assertEqual(versioning.read_version(), "2.60")
        with mock.patch.object(versioning, "_read_text", side_effect=AssertionError("served from cache")):
            self.assertEqual(versioning.read_version(), "2.60")  # بی‌خواندنِ دیسک
        p.write_text("2.61\n", encoding="utf-8")
        os.utime(p, (time.time() + 5, time.time() + 5))  # زمانِ تغییرِ متفاوت، حتی روی دیسکِ کم‌دقت
        self.assertEqual(versioning.read_version(), "2.61")

    def test_cached_value_is_a_copy(self):
        self.write("CHANGELOG-fa.md", SAMPLE)
        a = versioning.read_changelog()
        a[0]["items"].append("آلوده")
        a.clear()
        self.assertEqual(len(versioning.read_changelog()), 2)
        self.assertNotIn("آلوده", versioning.read_changelog()[0]["items"])

    def test_jalali_conversion(self):
        self.assertEqual(versioning.built_at_fa("2026-11-07T05:30:00Z"), "۱۴۰۵/۰۸/۱۶")
        # ۲۱:۰۰ UTC = ۰۰:۳۰ بامدادِ روزِ بعد در تهران ⇒ یک روز جلوتر
        self.assertEqual(versioning.built_at_fa("2026-11-07T21:00:00Z"), "۱۴۰۵/۰۸/۱۷")
        self.assertEqual(versioning.built_at_fa("2026-11-07T20:29:59Z"), "۱۴۰۵/۰۸/۱۶")
        self.assertEqual(versioning.built_at_fa("garbage"), "")
        self.assertEqual(versioning.built_at_fa(None), "")


class ChangelogParserTests(SimpleTestCase):
    def test_sample(self):
        entries = versioning.parse_changelog(SAMPLE)
        self.assertEqual([e["version"] for e in entries], ["2.60", "2.59"])
        first = entries[0]
        self.assertEqual(first["date"], "۱۴۰۵/۰۸/۱۶")
        self.assertEqual(first["summary"], "نوشتهٔ کوتاهِ زیرِ تیتر.")
        self.assertEqual(
            first["items"],
            ["صفِ پردازشِ ماندگار برای کارهای سنگین", "گزارشِ سرورها که در دو خط نوشته شده", "دانلودِ زمان‌بندی‌شده", "نشانِ نسخه"],
        )
        self.assertEqual(entries[1]["date"], "")
        self.assertEqual(entries[1]["items"], ["فقط یک خط"])

    def test_non_text_inputs(self):
        for bad in [None, 5, [], {}, b"", b"\xff\xfe\xfa", "", "   \n  ", "no headings at all\n- just bullets"]:
            self.assertIsInstance(versioning.parse_changelog(bad), list)
        self.assertEqual(versioning.parse_changelog(None), [])
        self.assertEqual(versioning.parse_changelog("- orphan bullet"), [])

    def test_bom_crlf_and_old_mac_newlines(self):
        text = "﻿## v2.60 — ۱۴۰۵/۰۸/۱۶\r\n- الف\r\n- ب\r\n"
        e = versioning.parse_changelog(text)
        self.assertEqual(e[0]["items"], ["الف", "ب"])
        e = versioning.parse_changelog("## v2.60\r- الف\r- ب")
        self.assertEqual(e[0]["items"], ["الف", "ب"])

    def test_bytes_input(self):
        e = versioning.parse_changelog(SAMPLE.encode("utf-8"))
        self.assertEqual(len(e), 2)

    def test_headings_variants(self):
        text = "## V3.00 - ۱۴۰۶/۰۱/۰۱\n- a\n## v۲.۹۹ – تاریخ دلخواه\n- b\n## v2.5\n- کوتاه است و نسخه نیست\n## 2.58: بی‌v\n- c\n"
        e = versioning.parse_changelog(text)
        self.assertEqual([x["version"] for x in e], ["3.00", "2.99", "2.58"])
        self.assertEqual(e[1]["date"], "تاریخ دلخواه")

    def test_caps(self):
        many = "".join(f"## v1.{i % 90 + 10}\n" + "".join(f"- x{j}\n" for j in range(150)) for i in range(300))
        e = versioning.parse_changelog(many)
        self.assertLessEqual(len(e), versioning.MAX_ENTRIES)
        self.assertLessEqual(len(e[0]["items"]), versioning.MAX_ITEMS)
        long_line = "## v2.60\n- " + "ی" * 5000 + "\n"
        self.assertLessEqual(len(versioning.parse_changelog(long_line)[0]["items"][0]), versioning.MAX_ITEM_CHARS)

    def test_real_changelog_in_repo_parses(self):
        path = REPO_ROOT / "CHANGELOG-fa.md"
        if not path.exists():
            self.skipTest("CHANGELOG-fa.md هنوز در ریشه نیست")
        entries = versioning.parse_changelog(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(entries), 1)
        self.assertEqual(entries[0]["version"], "2.60")
        self.assertGreaterEqual(len(entries[0]["items"]), 4)
        self.assertRegex(entries[0]["date"], r"^[۰-۹]{4}/[۰-۹]{2}/[۰-۹]{2}$")


class EndpointTests(_TempRoot):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_version_is_public_and_shaped(self):
        self.write("VERSION", "2.60\n")
        self.write("build.json", json.dumps({"version": "2.60", "built_at": "2026-11-07T05:30:00Z", "commit": "abc1234"}))
        r = self.client.get("/api/v1/version/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"version": "2.60", "built_at": "2026-11-07T05:30:00Z", "commit": "abc1234", "name": "NMarketing"})
        self.assertIn("max-age", r["Cache-Control"])

    def test_version_ignores_a_stale_or_garbage_token(self):
        self.write("VERSION", "2.60\n")
        for header in ["Bearer not.a.real.token", "Bearer ", "Basic Zm9vOmJhcg==", "Token xyz"]:
            r = self.client.get("/api/v1/version/", HTTP_AUTHORIZATION=header)
            self.assertEqual(r.status_code, 200, msg=header)
            self.assertEqual(r.json()["version"], "2.60")
            r = self.client.get("/api/v1/version/changelog/", HTTP_AUTHORIZATION=header)
            self.assertEqual(r.status_code, 200, msg=header)

    def test_version_without_files_is_200_with_empty_version(self):
        r = self.client.get("/api/v1/version/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["version"], "")
        self.assertEqual(r.json()["name"], "NMarketing")

    def test_changelog_entries(self):
        self.write("VERSION", "2.60\n")
        self.write("CHANGELOG-fa.md", SAMPLE)
        r = self.client.get("/api/v1/version/changelog/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["current"], "2.60")
        self.assertEqual(body["name"], "NMarketing")
        self.assertEqual([e["version"] for e in body["entries"]], ["2.60", "2.59"])
        self.assertEqual(body["entries"][0]["date"], "۱۴۰۵/۰۸/۱۶")
        # فارسی خام در JSON (نه \\u escape) هم درست برمی‌گردد
        self.assertIn("ماندگار", r.content.decode("utf-8"))

    def test_changelog_garbage_file_is_empty_list_not_500(self):
        self.write("CHANGELOG-fa.md", b"\x00\xff\xfe## v2.60\n\x80", binary=True)
        r = self.client.get("/api/v1/version/changelog/")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json()["entries"], list)

    def test_changelog_missing_file(self):
        r = self.client.get("/api/v1/version/changelog/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["entries"], [])

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post("/api/v1/version/", {}).status_code, 405)

    def test_settings_exposes_nm_version(self):
        from django.conf import settings

        self.assertTrue(hasattr(settings, "NM_VERSION"))
        self.assertIsInstance(settings.NM_VERSION, str)

    def test_admin_login_page_shows_the_badge(self):
        """سرصفحهٔ ادمین (حتی صفحهٔ ورود) پیوندِ «v2.60» به /panel/changelog دارد."""
        self.write("VERSION", "2.60\n")
        self.write("build.json", json.dumps({"version": "2.60", "built_at": "2026-11-07T05:30:00Z", "commit": "abc1234"}))
        html = self.client.get("/admin/login/").content.decode("utf-8")
        self.assertIn('class="nm-ver"', html)
        self.assertIn('href="/panel/changelog"', html)
        self.assertIn(">v2.60</a>", html)
        self.assertIn("ساخته‌شده: ۱۴۰۵/۰۸/۱۶", html)
        self.assertIn("commit abc1234", html)

    def test_admin_without_version_has_no_badge_and_still_renders(self):
        r = self.client.get("/admin/login/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('class="nm-ver"', r.content.decode("utf-8"))

    def test_admin_context_never_raises(self):
        self.write("VERSION", "2.60\n")
        self.write("build.json", json.dumps({"version": "2.60", "built_at": "2026-11-07T05:30:00Z", "commit": ""}))
        ctx = versioning.admin_context()
        self.assertEqual(ctx["nm_version"], "2.60")
        self.assertEqual(ctx["nm_built_fa"], "۱۴۰۵/۰۸/۱۶")
        shutil.rmtree(self.tmp)
        versioning.clear_cache()
        self.assertEqual(versioning.admin_context()["nm_version"], "")


@unittest.skipUnless(shutil.which("bash") and BUMP.exists(), "bash یا bump-version.sh در دسترس نیست")
class BumpScriptTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="nm-bump-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "backend").mkdir()
        (self.root / "backend" / "app.py").write_text("print(1)\n", encoding="utf-8")
        (self.root / "frontend" / "src").mkdir(parents=True)
        (self.root / "frontend" / "src" / "a.tsx").write_text("export {}\n", encoding="utf-8")

    def run_bump(self, *args, repo=None):
        env = dict(os.environ, NM_ROOT=str(self.root), NM_VERSION_REPO=str(repo or (self.root / "no-repo")))
        env.pop("NM_VERSION_DIR", None)
        return subprocess.run(["bash", str(BUMP), *args], env=env, capture_output=True, text=True, timeout=60)

    def version(self):
        return (self.root / "VERSION").read_text(encoding="utf-8").strip()

    def build(self):
        return json.loads((self.root / "build.json").read_text(encoding="utf-8"))

    def test_plain_bump_increments_minor_and_writes_build_json(self):
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        r = self.run_bump()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.version(), "2.61")
        b = self.build()
        self.assertEqual(b["version"], "2.61")
        self.assertRegex(b["built_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(b["commit"], "")  # مخزنی نیست ⇒ "" و بی‌خطا

    def test_rollover_299_to_300_and_leading_zero(self):
        for before, after in [("2.99", "3.00"), ("2.09", "2.10"), ("9.99", "10.00"), ("2.00", "2.01")]:
            (self.root / "VERSION").write_text(before + "\n", encoding="utf-8")
            self.assertEqual(self.run_bump().returncode, 0)
            self.assertEqual(self.version(), after, msg=before)
            self.assertEqual(self.build()["version"], after)

    def test_missing_version_starts_at_260(self):
        self.assertEqual(self.run_bump().returncode, 0)
        self.assertEqual(self.version(), "2.60")
        self.assertEqual(self.build()["version"], "2.60")

    def test_invalid_version_is_left_alone_and_exits_zero(self):
        for junk in ["abc", "2.6", "2.60.1", "٢.٦٠"]:
            (self.root / "VERSION").write_text(junk + "\n", encoding="utf-8")
            r = self.run_bump()
            self.assertEqual(r.returncode, 0, msg=junk)
            self.assertEqual((self.root / "VERSION").read_text(encoding="utf-8").strip(), junk)
            self.assertFalse((self.root / "build.json").exists())

    def test_unwritable_root_does_not_fail(self):
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        r = subprocess.run(
            ["bash", str(BUMP), "--quiet"],
            env=dict(os.environ, NM_ROOT=str(self.root / "does-not-exist"), NM_VERSION_REPO=str(self.root / "x")),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 0)

    def test_if_changed_baseline_then_noop_then_bump(self):
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        # اولین اجرا: خط‌مبنا؛ نسخه عوض نمی‌شود، ولی build.json ساخته می‌شود
        self.assertEqual(self.run_bump("--if-changed").returncode, 0)
        self.assertEqual(self.version(), "2.60")
        self.assertTrue((self.root / "data" / ".version-tree-hash").exists())
        self.assertEqual(self.build()["version"], "2.60")
        # بی‌تغییر ⇒ هر چند بار هم که بیاید، نسخه همان است
        for _ in range(3):
            r = self.run_bump("--if-changed")
            self.assertEqual(r.returncode, 0)
            self.assertEqual(self.version(), "2.60")
        # کد عوض شد ⇒ یک بار بالا می‌رود
        (self.root / "backend" / "app.py").write_text("print(2)  # changed\n", encoding="utf-8")
        os.utime(self.root / "backend" / "app.py", (time.time() + 10, time.time() + 10))
        self.assertEqual(self.run_bump("--if-changed").returncode, 0)
        self.assertEqual(self.version(), "2.61")
        # و دوباره بی‌تغییر ⇒ ثابت (خودِ bump انگشت‌نگار را به‌هم نمی‌زند)
        self.assertEqual(self.run_bump("--if-changed").returncode, 0)
        self.assertEqual(self.version(), "2.61")

    def test_noise_does_not_count_as_change(self):
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        self.run_bump("--if-changed")
        (self.root / "backend" / "__pycache__").mkdir()
        (self.root / "backend" / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
        (self.root / "backend" / "settings.py.bak-20261107").write_text("old", encoding="utf-8")
        (self.root / "backend" / ".env").write_text("SECRET=1", encoding="utf-8")
        (self.root / "backend" / "media").mkdir()
        (self.root / "backend" / "media" / "u.png").write_text("png", encoding="utf-8")
        (self.root / "frontend" / "dist").mkdir()
        (self.root / "frontend" / "dist" / "index.html").write_text("<html>", encoding="utf-8")
        (self.root / "logs").mkdir()
        (self.root / "logs" / "web.log").write_text("line", encoding="utf-8")
        (self.root / "build.json").write_text("{}", encoding="utf-8")
        self.run_bump("--if-changed")
        self.assertEqual(self.version(), "2.60")

    def test_plain_bump_updates_baseline_so_next_if_changed_is_noop(self):
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        self.run_bump()
        self.assertEqual(self.version(), "2.61")
        self.run_bump("--if-changed")
        self.assertEqual(self.version(), "2.61")

    def test_dry_run_writes_nothing(self):
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        r = self.run_bump("--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("2.61", r.stdout)
        self.assertEqual(self.version(), "2.60")
        self.assertFalse((self.root / "build.json").exists())
        self.assertFalse((self.root / "data" / ".version-tree-hash").exists())

    def test_commit_from_repo_head(self):
        if not shutil.which("git"):
            self.skipTest("git نیست")
        repo = self.root / "repo"
        repo.mkdir()
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for cmd in (["git", "init", "-q"], ["git", "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(cmd, cwd=repo, env=env, capture_output=True, check=True)
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        self.run_bump(repo=repo)
        self.assertEqual(self.build()["commit"], head)
        self.assertRegex(head, r"^[0-9a-f]{4,}$")

    def test_show(self):
        (self.root / "VERSION").write_text("2.60\n", encoding="utf-8")
        r = self.run_bump("--show")
        self.assertEqual(r.stdout.strip(), "2.60")
        self.assertEqual(self.version(), "2.60")

    def test_end_to_end_with_versioning_module(self):
        (self.root / "VERSION").write_text("2.99\n", encoding="utf-8")
        self.run_bump()
        with mock.patch.dict(os.environ, {"NM_VERSION_DIR": str(self.root)}):
            versioning.clear_cache()
            self.addCleanup(versioning.clear_cache)
            b = versioning.read_build()
        self.assertEqual(b["version"], "3.00")
        self.assertRegex(b["built_at"], r"^\d{4}-")
