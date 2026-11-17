# -*- coding: utf-8 -*-
"""«تصویر به کد» — کارِ پس‌زمینه (پردازهٔ جدا با سقفِ حافظه/زمان)، API، مجوزِ هر فروشگاه، ساختِ پیش‌نویس در سایت‌ساز، و یک تبدیلِ واقعیِ کوچک.

پردازهٔ runner در بیشترِ آزمون‌ها «ساختگی» است (services.run_process با تابعی عوض می‌شود که همان فایل‌هایی را می‌نویسد که runner می‌نویسد)؛
چند آزمون هم runner و بستهٔ mv2code را واقعی اجرا می‌کنند و اگر موتور/Tesseract/مرورگر روی ماشین نباشد رد می‌شوند (skip، نه شکست).
"""
import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image, ImageDraw, ImageFont
from rest_framework.test import APITestCase

from apps.brandchar.models import SiteBinding
from apps.projects.models import Design, Page, Project, SiteTheme
from apps.stores.models import Membership, Store

from . import services
from .models import Conversion
from .tests_mapping import landing_tree

READY = {"ok": True, "mv2code": "2.0.0", "tesseract": {"path": "/usr/bin/tesseract", "fas": True, "eng": True}, "pytesseract": True, "playwright": True, "chrome": "/x/chrome"}
SCORES = {"ssim": 0.9123, "pixel_similarity": 0.9301, "editable_share": 0.998, "rendered_size": [1280, 1400], "real_text_chars": 412}


def png_bytes(w=640, h=480, color=(240, 244, 250)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def upload(data=None, name="shot.png", ctype="image/png"):
    return SimpleUploadedFile(name, data if data is not None else png_bytes(), content_type=ctype)


def fake_runner(calls=None, fail=None):
    """همان فایل‌هایی را می‌نویسد که runner.py می‌نویسد."""
    def fn(args, timeout, mem=0, tick=None):
        args = [str(a) for a in args]
        if calls is not None:
            calls.append(args)
        cmd = args[0]
        if fail and fail.get(cmd):
            return fail[cmd]
        if cmd == "probe":
            return dict(READY)
        if cmd == "shot":
            out = Path(args[args.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png_bytes(1280, 1400))
            if "--lines-out" in args:
                Path(args[args.index("--lines-out") + 1]).write_text(json.dumps([{"box": [10, 10, 100, 20], "text": "متنِ صفحه", "conf": 1.0}]), encoding="utf-8")
            return {"ok": True, "width": 1280, "height": 1400, "title": "عنوانِ صفحه", "final_url": "https://example.com/", "truncated": False, "dom_lines": 1, "blocked_requests": []}
        if cmd == "convert":
            out = Path(args[args.index("--outdir") + 1])
            (out / "fonts").mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text("<!doctype html><html lang=fa dir=rtl><body><h1>فروشگاهِ نمونه</h1></body></html>", encoding="utf-8")
            (out / "style.css").write_text("body{margin:0}", encoding="utf-8")
            (out / "fonts" / "f.woff2").write_bytes(b"wOF2")
            tree = landing_tree()
            (out / "tree.json").write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
            (out / "report.json").write_text("{}", encoding="utf-8")
            (out / "original.png").write_bytes(png_bytes(1280, 1400))
            return {"ok": True, "report": {"version": "2.0.0", "mode": "responsive", "page_direction": "rtl", "ocr": "tesseract", "text_lines": 12, "nodes": 40, "regions": 7,
                                           "seconds": {"total": 3.2}}, "size": [1280, 1400], "scale": 1.0}
        if cmd == "render":
            out = Path(args[args.index("--dir") + 1])
            (out / "rendered.png").write_bytes(png_bytes(1280, 1400, (250, 250, 250)))
            return {"ok": True, "scores": dict(SCORES), "rendered": "rendered.png"}
        raise AssertionError(cmd)
    return fn


class Base(APITestCase):
    databases = {"default", "studio"}          # سایت‌ساز پایگاهِ جدا دارد

    def setUp(self):
        services._PROBE.update(at=0.0, data=None)
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-img2code-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.override = override_settings(NM_DATA_DIR=self.tmp / "data", WORKSPACES_ROOT=self.tmp / "work")
        self.override.enable()
        self.addCleanup(self.override.disable)
        (self.tmp / "work").mkdir(parents=True, exist_ok=True)
        self.owner = User.objects.create_user("i2c-owner", password="x")
        self.stranger = User.objects.create_user("i2c-stranger", password="x")
        self.viewer = User.objects.create_user("i2c-viewer", password="x")
        self.staff = User.objects.create_user("i2c-staff", password="x", is_staff=True)
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ نمونه")
        self.other = Store.objects.create(owner=self.stranger, name="فروشگاهِ دیگر")
        self.staff_store = Store.objects.create(owner=self.staff, name="فروشگاهِ کارمند")
        Membership.objects.create(store=self.store, user=self.viewer, role=Membership.Role.VIEWER)
        p = mock.patch.object(services, "run_process", side_effect=fake_runner())
        self.runner = p.start()
        self.addCleanup(p.stop)

    def url(self, store, tail=""):
        return "/api/v1/stores/%d/image-to-code/%s" % (store.pk, tail)

    def make(self, store, user, **extra):
        self.client.force_authenticate(user)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url(store), {"image": upload(), **extra}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["item"]


class PermissionTests(Base):
    def test_a_stranger_cannot_see_or_touch_another_stores_conversions(self):
        item = self.make(self.store, self.owner)
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.get(self.url(self.store)).status_code, 404)
        self.assertEqual(self.client.get(self.url(self.store, "%d/" % item["id"])).status_code, 404)
        self.assertEqual(self.client.delete(self.url(self.store, "%d/" % item["id"])).status_code, 404)
        self.assertEqual(self.client.get(self.url(self.store, "%d/files/original.png" % item["id"])).status_code, 404)
        # و از راهِ فروشگاهِ خودش هم به آن نمی‌رسد
        self.assertEqual(self.client.get(self.url(self.other, "%d/" % item["id"])).status_code, 404)

    def test_anonymous_is_refused(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url(self.store)).status_code, (401, 403))

    def test_a_viewer_can_read_but_not_create_delete_or_cancel(self):
        item = self.make(self.store, self.owner)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.url(self.store)).status_code, 200)
        self.assertEqual(self.client.get(self.url(self.store, "%d/" % item["id"])).status_code, 200)
        self.assertEqual(self.client.post(self.url(self.store), {"image": upload()}, format="multipart").status_code, 403)
        self.assertEqual(self.client.delete(self.url(self.store, "%d/" % item["id"])).status_code, 403)
        self.assertEqual(self.client.post(self.url(self.store, "%d/cancel/" % item["id"])).status_code, 403)

    def test_history_is_per_store(self):
        a = self.make(self.store, self.owner)
        b = self.make(self.other, self.stranger)
        self.client.force_authenticate(self.owner)
        ids = [i["id"] for i in self.client.get(self.url(self.store)).json()["items"]]
        self.assertEqual(ids, [a["id"]])
        self.assertNotIn(b["id"], ids)

    def test_site_draft_is_for_staff_only_even_for_the_stores_owner(self):
        item = self.make(self.store, self.owner)
        self.client.force_authenticate(self.owner)
        r = self.client.post(self.url(self.store, "%d/site-draft/" % item["id"]), {}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "staff_only")
        self.assertEqual(self.client.get(self.url(self.store, "%d/site-targets/" % item["id"])).status_code, 403)
        self.assertFalse(Project.objects.exists())

    def test_overview_tells_the_ui_whether_the_site_builder_button_applies(self):
        self.client.force_authenticate(self.owner)
        self.assertFalse(self.client.get(self.url(self.store)).json()["can_draft"])
        self.client.force_authenticate(self.staff)
        self.assertTrue(self.client.get(self.url(self.staff_store)).json()["can_draft"])


class CreateTests(Base):
    def test_upload_runs_the_whole_pipeline_in_the_background_and_scores_are_persian(self):
        item = self.make(self.store, self.owner, mode="exact", lang="fa", title="آزمون")
        self.assertEqual(item["mode"], "exact")
        self.assertEqual(item["lang"], "fa")
        conv = Conversion.objects.get(pk=item["id"])
        self.assertEqual(conv.state, "READY", conv.error)
        got = {s["key"]: s for s in conv.scores}
        self.assertEqual(got["ssim"]["display"], "۹۱٪")
        self.assertEqual(got["ssim"]["verdict"], "good")
        self.assertIn("شباهت", got["ssim"]["label"])
        self.assertEqual(got["editable"]["display"], "۱۰۰٪")
        self.assertEqual(got["text_source"]["display"], "با OCR (Tesseract)")
        self.assertTrue(any("OCR" in w for w in conv.warnings))              # برای فارسیِ راست‌به‌چپ هشدارِ OCR
        self.assertEqual(conv.size_w, 1280)
        cmds = [c.args[0][0] for c in self.runner.call_args_list]
        self.assertIn("convert", cmds)
        self.assertIn("render", cmds)

    def test_mode_and_lang_reach_the_runner(self):
        calls = []
        self.runner.side_effect = fake_runner(calls)
        self.make(self.store, self.owner, mode="exact", lang="en")
        conv_args = next(c for c in calls if c[0] == "convert")
        self.assertEqual(conv_args[conv_args.index("--mode") + 1], "exact")
        self.assertEqual(conv_args[conv_args.index("--lang") + 1], "en")

    def test_bad_inputs_are_refused_with_persian_messages(self):
        self.client.force_authenticate(self.owner)
        for data, code in ((b"not an image at all", "bad_image"), (png_bytes(20, 20), "small_image")):
            r = self.client.post(self.url(self.store), {"image": upload(data)}, format="multipart")
            self.assertEqual(r.status_code, 400, r.content)
            self.assertEqual(r.json()["error"]["code"], code)
        gif = io.BytesIO()
        Image.new("RGB", (300, 300)).save(gif, "BMP")
        self.assertEqual(self.client.post(self.url(self.store), {"image": upload(gif.getvalue(), "a.bmp")}, format="multipart").json()["error"]["code"], "bad_image")
        self.assertEqual(self.client.post(self.url(self.store), {}, format="json").json()["error"]["code"], "no_input")
        with mock.patch.object(services, "MAX_UPLOAD_BYTES", 1000):
            r = self.client.post(self.url(self.store), {"image": upload()}, format="multipart")
            self.assertEqual(r.json()["error"]["code"], "big_file")
        with mock.patch.object(services, "MAX_PIXELS", 10_000):
            self.assertEqual(self.client.post(self.url(self.store), {"image": upload()}, format="multipart").json()["error"]["code"], "big_image")
        self.assertEqual(Conversion.objects.count(), 0)

    def test_url_to_internal_addresses_is_refused_before_any_work(self):
        self.client.force_authenticate(self.owner)
        for u in ("http://127.0.0.1:8041/admin/", "http://169.254.169.254/latest/", "http://localhost/", "file:///etc/passwd", "https://u:p@example.com/"):
            r = self.client.post(self.url(self.store), {"url": u}, format="json")
            self.assertEqual(r.status_code, 400, (u, r.content))
            self.assertEqual(r.json()["error"]["code"], "url_refused", u)
        self.assertEqual(Conversion.objects.count(), 0)

    def test_url_conversion_takes_the_screenshot_then_reads_the_text_from_the_page(self):
        calls = []
        self.runner.side_effect = fake_runner(calls)
        self.client.force_authenticate(self.owner)
        with mock.patch("apps.img2code.netguard.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(self.url(self.store), {"url": "example.com/page", "mode": "responsive", "width": 768}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        conv = Conversion.objects.get(pk=r.json()["item"]["id"])
        self.assertEqual(conv.state, "READY", conv.error)
        self.assertEqual(conv.source_url, "https://example.com/page")
        self.assertEqual(conv.title, "عنوانِ صفحه")
        shot = next(c for c in calls if c[0] == "shot")
        self.assertEqual(shot[shot.index("--width") + 1], "768")
        self.assertIn("--lines-out", shot)
        convert = next(c for c in calls if c[0] == "convert")
        self.assertIn("--lines", convert)
        self.assertEqual({s["key"]: s for s in conv.scores}["text_source"]["display"], "از خودِ صفحه (دقیق)")
        self.assertFalse(any("OCR" in w for w in conv.warnings))

    def test_runner_failure_is_reported_in_persian_and_the_row_is_failed(self):
        self.runner.side_effect = fake_runner(fail={"convert": {"ok": False, "error": "bad_image", "message": "این فایل تصویرِ قابلِ خواندنی نیست."}})
        item = self.make(self.store, self.owner)
        conv = Conversion.objects.get(pk=item["id"])
        self.assertEqual(conv.state, "FAILED")
        self.assertIn("تصویرِ قابلِ خواندنی نیست", conv.error)

    def test_a_failed_render_keeps_the_code_and_says_so(self):
        self.runner.side_effect = fake_runner(fail={"render": {"ok": False, "error": "render_failed", "message": "نتیجه در مرورگر نمایش داده نشد."}})
        item = self.make(self.store, self.owner)
        conv = Conversion.objects.get(pk=item["id"])
        self.assertEqual(conv.state, "READY")
        self.assertTrue(any("نمایش داده نشد" in w for w in conv.warnings))
        self.assertFalse(conv.scores and any(s["key"] == "ssim" for s in conv.scores))

    def test_engine_missing_gives_a_clear_503(self):
        self.runner.side_effect = fake_runner(fail={"probe": {"ok": True, "mv2code": None}})
        self.client.force_authenticate(self.owner)
        r = self.client.post(self.url(self.store), {"image": upload()}, format="multipart")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "engine_missing")
        self.assertIn("install-img2code", r.json()["error"]["message"])

    def test_history_cap_and_active_cap(self):
        self.client.force_authenticate(self.owner)
        with mock.patch.object(services, "HISTORY_CAP", 2):
            self.make(self.store, self.owner)
            self.make(self.store, self.owner)
            r = self.client.post(self.url(self.store), {"image": upload()}, format="multipart")
            self.assertEqual(r.status_code, 409)
            self.assertEqual(r.json()["error"]["code"], "history_full")
        Conversion.objects.all().delete()
        for _ in range(3):
            Conversion.objects.create(store=self.store, state="QUEUED")
        r = self.client.post(self.url(self.store), {"image": upload()}, format="multipart")
        self.assertEqual(r.json()["error"]["code"], "too_many_active")

    def test_again_reuses_the_same_image_with_the_other_mode(self):
        item = self.make(self.store, self.owner, mode="responsive")
        self.client.force_authenticate(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url(self.store, "%d/again/" % item["id"]), {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        new = r.json()["item"]
        self.assertEqual(new["mode"], "exact")
        self.assertNotEqual(new["id"], item["id"])
        self.assertTrue((Conversion.objects.get(pk=new["id"]).dir / "source.png").exists())


class ResultTests(Base):
    def setUp(self):
        super().setUp()
        self.item = self.make(self.store, self.owner)
        self.conv = Conversion.objects.get(pk=self.item["id"])
        self.client.force_authenticate(self.owner)

    def test_files_zip_and_code(self):
        r = self.client.get(self.url(self.store, "%d/files/original.png" % self.conv.pk))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(self.client.get(self.url(self.store, "%d/files/rendered.png" % self.conv.pk)).status_code, 200)
        z = self.client.get(self.url(self.store, "%d/files/result.zip" % self.conv.pk))
        self.assertEqual(z.status_code, 200)
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
        for n in ("index.html", "tree.json", "report.json", "original.png", "rendered.png", "fonts/f.woff2"):
            self.assertIn(n, names)
        code = self.client.get(self.url(self.store, "%d/code/" % self.conv.pk)).json()
        self.assertIn("فروشگاهِ نمونه", code["html"])
        self.assertIn("margin:0", code["css"])
        self.assertIn('"role"', code["tree"])

    def test_html_is_only_ever_a_sandboxed_download(self):
        r = self.client.get(self.url(self.store, "%d/files/index.html" % self.conv.pk))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("sandbox", r["Content-Security-Policy"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_only_listed_files_are_served_and_no_path_tricks(self):
        for name in ("..%2F..%2Fsource.png", "passwd", "run.lock", "fonts", "lines.json", "%2e%2e/original.png"):
            self.assertIn(self.client.get(self.url(self.store, "%d/files/%s" % (self.conv.pk, name))).status_code, (404, 301))

    def test_delete_removes_row_and_files(self):
        d = self.conv.dir
        self.assertTrue(d.exists())
        self.assertEqual(self.client.delete(self.url(self.store, "%d/" % self.conv.pk)).status_code, 204)
        self.assertFalse(Conversion.objects.filter(pk=self.conv.pk).exists())
        self.assertFalse(d.exists())

    def test_cancel_stops_a_queued_job_and_the_runner_is_not_started(self):
        c = Conversion.objects.create(store=self.store, state="QUEUED")
        r = self.client.post(self.url(self.store, "%d/cancel/" % c.pk))
        self.assertEqual(r.json()["item"]["state"], "CANCELLED")
        self.runner.reset_mock()
        from . import tasks
        tasks.run_conversion(c.pk)
        self.runner.assert_not_called()

    def test_sweep_fails_stuck_jobs_and_removes_orphan_directories(self):
        from datetime import timedelta
        from django.utils import timezone
        stuck = Conversion.objects.create(store=self.store, state="RUNNING")
        Conversion.objects.filter(pk=stuck.pk).update(updated_at=timezone.now() - timedelta(hours=2))
        orphan = self.conv.dir.parent / "conv99999"
        orphan.mkdir(parents=True)
        out = services.sweep()
        self.assertEqual(out["stale"], 1)
        self.assertEqual(out["removed_dirs"], 1)
        self.assertFalse(orphan.exists())
        stuck.refresh_from_db()
        self.assertEqual(stuck.state, "FAILED")
        self.assertTrue(self.conv.dir.exists())

    def test_only_one_conversion_runs_at_a_time(self):
        lock = services.RunLock()
        self.assertTrue(lock.acquire())
        try:
            other = services.RunLock()
            if services.fcntl is not None:
                self.assertFalse(other.acquire(), "قفل باید نگه داشته شود")
            from celery.exceptions import Retry
            from . import tasks
            c = Conversion.objects.create(store=self.store, state="QUEUED")
            if services.fcntl is not None:
                with self.assertRaises(Retry):
                    tasks.run_conversion.run(c.pk)
        finally:
            lock.release()


class QueueOrderAndCleanupTests(Base):
    """صف «اولین وارد، اولین خارج»، حذفِ تبدیلِ در حال اجرا بی‌ردِ خطا، و پیش‌نمایشِ سبک."""

    def queued(self, n):
        return [Conversion.objects.create(store=self.store, state="QUEUED") for _ in range(n)]

    def test_a_newer_conversion_never_jumps_ahead_of_an_older_waiting_one(self):
        a, b, c = self.queued(3)
        self.assertTrue(services.is_my_turn(a))
        self.assertFalse(services.is_my_turn(b))
        self.assertFalse(services.is_my_turn(c))
        a.state = "RUNNING"
        a.save()
        self.assertTrue(services.is_my_turn(b))          # قدیمی‌تر در حال اجراست (در صف نیست)؛ قفل جلوی همزمانی را می‌گیرد
        self.assertFalse(services.is_my_turn(c))

    def test_a_dead_waiter_does_not_block_the_line_forever(self):
        from datetime import timedelta
        from django.utils import timezone
        a, b = self.queued(2)
        Conversion.objects.filter(pk=a.pk).update(updated_at=timezone.now() - timedelta(seconds=services.WAIT_FRESH_SECONDS + 30))
        self.assertTrue(services.is_my_turn(b))

    def test_the_task_waits_while_an_older_one_is_queued_and_says_so(self):
        from celery.exceptions import Retry
        from . import tasks
        a, b = self.queued(2)
        with self.assertRaises(Retry):
            tasks.run_conversion.run(b.pk)
        b.refresh_from_db()
        self.assertIn("نوبتِ 2", b.message)
        self.assertEqual(b.state, "QUEUED")

    def test_queue_position_follows_creation_order(self):
        a, b, c = self.queued(3)
        self.assertEqual([services.queue_position(x) for x in (a, b, c)], [1, 2, 3])

    def test_deleting_a_conversion_while_it_runs_ends_quietly(self):
        item = self.make(self.store, self.owner)
        conv = Conversion.objects.get(pk=item["id"])
        Conversion.objects.filter(pk=conv.pk).update(state="QUEUED")
        conv.refresh_from_db()
        base = fake_runner()

        def deleting(args, timeout, mem=0, tick=None):
            r = base(args, timeout, mem, tick)
            if args[0] == "convert":
                services.delete(Conversion.objects.get(pk=conv.pk))          # کاربر وسطِ کار «حذف» را زد
            return r
        with mock.patch.object(services, "run_process", side_effect=deleting), mock.patch.object(services, "log") as lg:
            services.run(conv)
        self.assertFalse(Conversion.objects.filter(pk=conv.pk).exists())
        self.assertFalse((self.tmp / "data" / "img2code" / ("conv%d" % conv.pk)).exists(), "پوشهٔ تبدیلِ حذف‌شده نباید بماند")
        self.assertFalse(lg.exception.called)

    def test_upload_conversion_passes_the_store_name_as_brand_glossary_but_a_url_with_dom_text_does_not(self):
        calls = []
        self.runner.side_effect = fake_runner(calls)
        self.make(self.store, self.owner)
        conv_args = next(a for a in calls if a[0] == "convert")
        self.assertIn("--glossary", conv_args)
        words = conv_args[conv_args.index("--glossary") + 1].split(",")
        self.assertIn("نمونه", words)
        calls.clear()
        self.client.force_authenticate(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url(self.store), {"url": "https://example.com/", "mode": "responsive"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        conv_args = next(a for a in calls if a[0] == "convert")
        self.assertIn("--lines", conv_args)
        self.assertNotIn("--glossary", conv_args)

    def test_brand_words_are_clean_and_bounded(self):
        c = Conversion(store=Store(name="چغر | مربی هوشمند — Chagher"), source_kind="upload", title="x")
        self.assertEqual(services.brand_words(c)[:3], ["چغر", "مربی", "هوشمند"])
        self.assertLessEqual(len(services.brand_words(Conversion(store=Store(name=" ".join("واژه%d" % i for i in range(40))), source_kind="upload"))), 12)

    def test_set_returns_false_for_a_deleted_row_instead_of_raising(self):
        c = Conversion.objects.create(store=self.store, state="RUNNING")
        ghost = Conversion.objects.get(pk=c.pk)
        c.delete()
        self.assertFalse(services._set(ghost, message="x"))

    def test_previews_are_small_webp_and_made_on_demand(self):
        item = self.make(self.store, self.owner)
        conv = Conversion.objects.get(pk=item["id"])
        big = Image.fromarray(np.random.default_rng(1).integers(0, 255, (1600, 1800, 3), dtype=np.uint8))
        big.save(conv.out_dir / "original.png")
        (conv.out_dir / "original.preview.webp").unlink(missing_ok=True)
        self.client.force_authenticate(self.owner)
        r = self.client.get(self.url(self.store, "%d/files/original.preview.webp" % conv.pk))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/webp")
        im = Image.open(io.BytesIO(b"".join(r.streaming_content)))
        self.assertEqual(im.format, "WEBP")
        self.assertEqual(im.width, services.PREVIEW_MAX_W)
        self.assertEqual(Image.open(conv.out_dir / "original.png").size, (1800, 1600))        # PNGِ کامل دست‌نخورده می‌ماند
        self.assertEqual(self.client.get(self.url(self.store, "%d/files/nothing.preview.webp" % conv.pk)).status_code, 404)

    def test_a_conversion_made_by_the_pipeline_has_its_previews(self):
        item = self.make(self.store, self.owner)
        conv = Conversion.objects.get(pk=item["id"])
        self.assertEqual(conv.state, "READY")
        self.assertTrue((conv.out_dir / "original.preview.webp").is_file())
        self.assertTrue((conv.out_dir / "rendered.preview.webp").is_file())

    def test_a_stranger_cannot_read_previews(self):
        item = self.make(self.store, self.owner)
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.get(self.url(self.store, "%d/files/original.preview.webp" % item["id"])).status_code, 404)


class SiteDraftTests(Base):
    def setUp(self):
        super().setUp()
        self.item = self.make(self.staff_store, self.staff)
        self.conv = Conversion.objects.get(pk=self.item["id"])
        # تصویرِ اصلیِ واقعی‌تر برای نمونه‌برداریِ رنگ و بریدنِ تصویرها
        im = np.full((1400, 1280, 3), (244, 246, 250), np.uint8)
        Image.fromarray(im).save(self.conv.out_dir / "original.png")
        tree = landing_tree()
        tree["children"].append({"id": 999, "role": "image", "box": [100, 1000, 300, 150], "embedded_raster": True})
        (self.conv.out_dir / "tree.json").write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
        self.client.force_authenticate(self.staff)

    def draft(self, **body):
        return self.client.post(self.url(self.staff_store, "%d/site-draft/" % self.conv.pk), body, format="json")

    def test_new_project_gets_page_header_footer_theme_and_stays_a_draft(self):
        r = self.draft()
        self.assertEqual(r.status_code, 201, r.content)
        out = r.json()
        p = Project.objects.get(slug=out["project_slug"])
        self.assertTrue(out["created_project"])
        self.assertTrue(SiteBinding.objects.filter(project_slug=p.slug, store=self.staff_store).exists())
        page = Page.objects.get(pk=out["page_id"])
        self.assertEqual(page.slug, "")
        self.assertEqual(page.body_html, "")                                           # چیزی رندر/منتشر نشده
        d = Design.objects.get(page=page)
        self.assertIsNone(d.published)
        self.assertIsNone(d.published_at)
        self.assertTrue(d.draft["blocks"])
        self.assertEqual({x.target for x in Design.objects.filter(project=p)}, {"page", "header", "footer"})
        theme = SiteTheme.objects.get(project=p)
        self.assertFalse(theme.active)
        self.assertEqual(theme.draft["colors"]["primary"], "#1b6ec2")
        self.assertEqual([m["label"] for m in theme.menu], ["خانه", "درباره ما", "تماس"])
        self.assertEqual(p.site_title, "فروشگاه")
        self.assertFalse(hasattr(p, "published_site") and p.published_site.state == "live")
        self.assertEqual(out["url"], "/tools/studio/p/%s/builder/page/%d" % (p.slug, page.pk))
        conv = Conversion.objects.get(pk=self.conv.pk)
        self.assertEqual((conv.draft_project_slug, conv.draft_page_id), (p.slug, page.pk))

    def test_texts_and_colours_reach_the_draft_and_images_go_to_the_media_library(self):
        out = self.draft().json()
        d = Design.objects.get(page_id=out["page_id"])
        flat = json.dumps(d.draft, ensure_ascii=False)
        for t in ("فروشگاهِ نمونه", "همه‌چیز برای شروعِ کار", "شروع کنید", "آماده‌اید شروع کنیم؟"):
            self.assertIn(t, flat)
        refs = [b["props"]["src"] for b in self.walk(d.draft["blocks"]) if b["type"] == "image"]
        self.assertTrue(refs and all(x.startswith("m:") for x in refs), refs)
        from apps.projects.models import MediaAsset
        n = MediaAsset.objects.filter(project__slug=out["project_slug"]).count()
        self.assertTrue(1 <= n <= out["stats"]["images"])           # تکه‌های هم‌محتوا یک فایل می‌شوند

    def walk(self, blocks):
        for b in blocks:
            yield b
            yield from self.walk(b.get("children") or [])

    def test_existing_bound_project_only_gets_a_new_page_and_keeps_its_theme(self):
        first = self.draft().json()
        theme_before = SiteTheme.objects.get(project__slug=first["project_slug"]).draft
        with self.captureOnCommitCallbacks(execute=True):
            again = self.client.post(self.url(self.staff_store, "%d/again/" % self.conv.pk), {}, format="json").json()["item"]
        conv2 = Conversion.objects.get(pk=again["id"])
        shutil.copy2(self.conv.out_dir / "tree.json", conv2.out_dir / "tree.json")
        shutil.copy2(self.conv.out_dir / "original.png", conv2.out_dir / "original.png")
        r = self.client.post(self.url(self.staff_store, "%d/site-draft/" % conv2.pk), {"project": first["project_slug"]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        out = r.json()
        self.assertFalse(out["created_project"])
        self.assertEqual(out["project_slug"], first["project_slug"])
        self.assertEqual(Project.objects.count(), 1)
        page = Page.objects.get(pk=out["page_id"])
        self.assertTrue(page.slug.startswith("from-image-"))
        self.assertFalse(page.in_menu)
        self.assertEqual(SiteTheme.objects.get(project__slug=first["project_slug"]).draft, theme_before)
        self.assertEqual(Design.objects.filter(project__slug=first["project_slug"], target="header").count(), 1)
        body = json.dumps(Design.objects.get(page=page).draft, ensure_ascii=False)
        # سربرگ و پابرگِ تصویر در صفحه نمی‌آید (پروژه خودش دارد؛ وگرنه دو سربرگ و دو پابرگ می‌شد) ولی متنِ بدنه می‌آید
        self.assertNotIn("درباره ما", body)
        self.assertNotIn("همهٔ حقوق محفوظ است", body)
        self.assertIn("همه‌چیز برای شروعِ کار", body)
        self.assertEqual(out["skipped"], {"header": 1, "footer": 1})
        self.assertTrue(any("سربرگِ تصویر در صفحه نیامد" in w for w in out["warnings"]))
        self.assertTrue(any("پابرگِ تصویر در صفحه نیامد" in w for w in out["warnings"]))
        self.assertNotIn("site_header", body)                   # هیچ سربرگِ دومی در بدنه نیست

    def test_a_project_not_bound_to_this_store_is_refused(self):
        stranger_project = Project.objects.create(name="دیگری")
        SiteBinding.objects.create(project_slug=stranger_project.slug, store=self.other)
        r = self.draft(project=stranger_project.slug)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "bad_project")
        r = self.draft(project="no-such-project")
        self.assertEqual(r.status_code, 404)

    def test_not_ready_conversion_cannot_become_a_draft(self):
        c = Conversion.objects.create(store=self.staff_store, state="RUNNING")
        r = self.client.post(self.url(self.staff_store, "%d/site-draft/" % c.pk), {}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "not_ready")

    def test_targets_list_only_this_stores_projects(self):
        first = self.draft().json()
        other = Project.objects.create(name="دیگری")
        SiteBinding.objects.create(project_slug=other.slug, store=self.other)
        t = self.client.get(self.url(self.staff_store, "%d/site-targets/" % self.conv.pk)).json()["targets"]
        self.assertEqual([x["slug"] for x in t], [first["project_slug"]])
        self.assertTrue(t[0]["has_header"] and t[0]["has_footer"])          # رابط به کاربر می‌گوید سربرگ/پابرگِ تصویر نمی‌آید

    def _second_conversion(self):
        with self.captureOnCommitCallbacks(execute=True):
            again = self.client.post(self.url(self.staff_store, "%d/again/" % self.conv.pk), {}, format="json").json()["item"]
        conv2 = Conversion.objects.get(pk=again["id"])
        for f in ("tree.json", "original.png"):
            shutil.copy2(self.conv.out_dir / f, conv2.out_dir / f)
        return conv2

    def test_existing_project_without_header_or_footer_gets_them_from_the_image_once(self):
        """پروژه‌ای که سربرگ/پابرگ ندارد همان بخش‌ها را از تصویر می‌گیرد (نه در بدنه)؛ پروژه‌ای که دارد نمی‌گیرد."""
        project = Project.objects.create(name="بی‌سربرگ")
        SiteBinding.objects.create(project_slug=project.slug, store=self.staff_store)
        from . import sitedraft
        self.assertFalse(sitedraft.project_has_part(project, "header"))
        out = self.draft(project=project.slug).json()
        self.assertFalse(out["created_project"])
        self.assertEqual(out["skipped"], {"header": 0, "footer": 0})
        self.assertEqual({d.target for d in Design.objects.filter(project=project)}, {"page", "header", "footer"})
        self.assertTrue(sitedraft.project_has_part(project, "header") and sitedraft.project_has_part(project, "footer"))
        body = json.dumps(Design.objects.get(page_id=out["page_id"]).draft, ensure_ascii=False)
        self.assertNotIn("همهٔ حقوق محفوظ است", body)                           # پابرگ در بدنه نیست؛ در سندِ پابرگ است
        self.assertTrue(Design.objects.get(project=project, target="header").draft["blocks"])
        self.assertTrue(Design.objects.get(project=project, target="footer").draft["blocks"])
        self.assertTrue(any("سربرگ نداشت" in w for w in out["warnings"]))
        # بار دوم: حالا سربرگ و پابرگ دارد ⇒ کنار گذاشته می‌شوند و سندهایشان دست نمی‌خورد
        before = Design.objects.get(project=project, target="header").draft
        conv2 = self._second_conversion()
        r = self.client.post(self.url(self.staff_store, "%d/site-draft/" % conv2.pk), {"project": project.slug}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["skipped"], {"header": 1, "footer": 1})
        self.assertEqual(Design.objects.get(project=project, target="header").draft, before)

    def test_existing_project_page_body_has_no_header_like_columns(self):
        """«کنار گذاشتن» جایگزینِ «داخلِ بدنه» است: در پروژهٔ موجود هیچ ستونِ سربرگ‌مانندی در بدنه نمی‌ماند."""
        first = self.draft().json()
        conv2 = self._second_conversion()
        out = self.client.post(self.url(self.staff_store, "%d/site-draft/" % conv2.pk), {"project": first["project_slug"]}, format="json").json()
        page = Design.objects.get(page_id=out["page_id"]).draft
        texts = " ".join(str((b.get("props") or {}).get("text") or (b.get("props") or {}).get("html") or "") for b in self.walk(page["blocks"]))
        for nav_text in ("خانه", "درباره ما", "تماس"):
            self.assertNotIn(nav_text, texts)


class UiDesignTests(Base):
    """«باز کردن در طراحیِ UI»: سندِ UI/UX در استودیوی طراحی (اگر روشن باشد)؛ همان بلوک‌های سایت‌ساز، تصویرها جای‌تصویر، چیزی منتشر نمی‌شود."""

    def setUp(self):
        super().setUp()
        self.item = self.make(self.store, self.owner)
        self.conv = Conversion.objects.get(pk=self.item["id"])
        Image.fromarray(np.full((1400, 1280, 3), (244, 246, 250), np.uint8)).save(self.conv.out_dir / "original.png")
        tree = landing_tree()
        tree["children"].append({"id": 999, "role": "image", "box": [100, 1000, 300, 150], "embedded_raster": True})
        (self.conv.out_dir / "tree.json").write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
        self.client.force_authenticate(self.owner)

    def ui(self, store=None, conv=None, **body):
        return self.client.post(self.url(store or self.store, "%d/ui-design/" % (conv or self.conv).pk), body, format="json")

    def test_button_is_absent_when_the_design_studio_is_off(self):
        with override_settings(IMG2CODE_UI_DESIGN=False):
            got = self.client.get(self.url(self.store, "%d/" % self.conv.pk)).json()["item"]
            self.assertIsNone(got.get("ui_design"))
            r = self.ui()
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json()["error"]["code"], "no_design_studio")

    def test_button_is_offered_when_the_studio_is_on_and_a_doc_is_made_from_the_tree(self):
        from apps.design_studio.models import DesignDoc
        with override_settings(IMG2CODE_UI_DESIGN=True):
            got = self.client.get(self.url(self.store, "%d/" % self.conv.pk)).json()["item"]["ui_design"]
            self.assertEqual(got, {"label": "باز کردن در طراحیِ UI", "path": None})
            r = self.ui()
            self.assertEqual(r.status_code, 201, r.content)
            out = r.json()
            doc = DesignDoc.objects.get(pk=out["doc_id"])
            self.assertEqual((doc.kind, doc.store_id), ("ui", self.store.pk))
            self.assertEqual(out["url"], "/stores/%d/design/ui/%d" % (self.store.pk, doc.pk))
            self.assertEqual(out["item"]["ui_design"]["path"], out["url"])
            frames = doc.data["frames"]
            self.assertEqual([f["device"] for f in frames], ["desktop", "phone"])
            flat = json.dumps(frames[0]["children"], ensure_ascii=False)
            for want in ("فروشگاهِ نمونه", "شروع کنید", "ویژگیِ 1", "آماده‌اید شروع کنیم؟"):         # متن‌ها واقعی‌اند
                self.assertIn(want, flat)
            self.assertNotIn("crop:", json.dumps(doc.data, ensure_ascii=False))                       # تصویر: جای‌تصویر، نه مرجعِ ناشناخته
            self.assertTrue(all(c.get("t") == "block" for c in frames[0]["children"]))
            self.assertEqual(doc.meta["img2code"]["conversion"], self.conv.pk)

    def test_the_doc_renders_in_the_studio_engine_and_survives_its_own_ops(self):
        """سند باید در موتورِ خودِ استودیو (صحنه) بدونِ خطا بنشیند و ویرایش‌پذیر باشد."""
        from apps.design_studio import services as ds, ui_doc, ui_frames
        from apps.design_studio.models import DesignDoc
        with override_settings(IMG2CODE_UI_DESIGN=True):
            doc = DesignDoc.objects.get(pk=self.ui().json()["doc_id"])
        info = ds.store_info(doc.store, doc.data.get("settings"))
        scene = ui_frames.build_scene(doc.data, info)
        self.assertGreaterEqual(len(scene["pages"]), 2)
        self.assertLessEqual(ui_doc.count_nodes(doc.data), ui_doc.MAX_NODES)
        out = ds.apply_ops(doc, [{"op": "add_node", "frame": doc.data["frames"][0]["id"], "type": "c_cta_center_box"}], doc.rev)
        self.assertEqual(out.rev, doc.rev + 1)

    def test_asking_twice_opens_the_same_doc_and_new_makes_another(self):
        from apps.design_studio.models import DesignDoc
        with override_settings(IMG2CODE_UI_DESIGN=True):
            a = self.ui()
            b = self.ui()
            self.assertEqual((a.status_code, b.status_code), (201, 200))
            self.assertEqual(a.json()["doc_id"], b.json()["doc_id"])
            self.assertFalse(b.json()["created"])
            c = self.ui(new=True)
            self.assertNotEqual(c.json()["doc_id"], a.json()["doc_id"])
            self.assertEqual(DesignDoc.objects.filter(store=self.store).count(), 2)
            DesignDoc.objects.filter(pk=c.json()["doc_id"]).delete()
            DesignDoc.objects.filter(pk=a.json()["doc_id"]).delete()               # سند را کاربر پاک کرد ⇒ دکمه دوباره می‌سازد
            again = self.client.get(self.url(self.store, "%d/" % self.conv.pk)).json()["item"]["ui_design"]
            self.assertIsNone(again["path"])

    def test_permissions_follow_the_studio_content_access(self):
        with override_settings(IMG2CODE_UI_DESIGN=True):
            self.client.force_authenticate(self.viewer)
            self.assertEqual(self.ui().status_code, 403)                                  # بیننده نمی‌نویسد
            self.client.force_authenticate(self.stranger)
            self.assertEqual(self.ui().status_code, 404)                                  # عضو نیست
            self.client.force_authenticate(None)
            self.assertEqual(self.ui().status_code, 401)
            self.client.force_authenticate(self.owner)
            self.assertEqual(self.ui().status_code, 201)                                  # مالک (غیرکارمند) هم می‌تواند: طراحیِ UI مثلِ استودیوست

    def test_not_ready_conversion_is_refused_and_nothing_is_published(self):
        from apps.design_studio.models import DesignDoc
        c = Conversion.objects.create(store=self.store, state="RUNNING")
        with override_settings(IMG2CODE_UI_DESIGN=True):
            r = self.ui(conv=c)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "not_ready"))
        self.assertFalse(DesignDoc.objects.exists())
        self.assertFalse(Project.objects.filter(name__contains="از تصویر").exists())


class DemoCommandTests(Base):
    """«manage.py img2code_demo --store 34»: نمونهٔ زنده برای مالک؛ فقط پیش‌نویس و ردیفِ تاریخچه می‌سازد."""

    def test_demo_command_builds_conversion_site_draft_and_ui_doc_without_publishing(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.design_studio.models import DesignDoc
        from . import tasks
        out = StringIO()
        with mock.patch("apps.img2code.netguard.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]), \
                mock.patch.object(services, "_enqueue", side_effect=lambda c: tasks.run_conversion(c.pk)), override_settings(IMG2CODE_UI_DESIGN=True):
            call_command("img2code_demo", "--store", str(self.staff_store.pk), "--user", self.staff.username, "--url", "https://example.com/", stdout=out, wait=20)
        text = out.getvalue()
        conv = Conversion.objects.get(store=self.staff_store)
        self.assertEqual(conv.state, "READY")
        self.assertIsNotNone(conv.draft_page_id)
        self.assertIsNotNone(conv.ui_doc_id)
        self.assertIn("/tools/studio/p/", text)
        self.assertIn("/stores/%d/design/ui/%d" % (self.staff_store.pk, conv.ui_doc_id), text)
        self.assertIsNone(Design.objects.get(page_id=conv.draft_page_id).published)         # هرگز منتشر نمی‌شود
        self.assertEqual(DesignDoc.objects.filter(store=self.staff_store).count(), 1)

    def test_demo_command_refuses_unknown_store(self):
        from django.core.management import CommandError, call_command
        with self.assertRaises(CommandError):
            call_command("img2code_demo", "--store", "999999")


# ───────────────────────────────────────────────────────────────── آزمونِ واقعی (بی‌ماک): runner + mv2code + Tesseract (+ مرورگر)
def _real_engine() -> dict:
    services._PROBE.update(at=0.0, data=None)
    return services.engine_status(refresh=True)


class RealConversionTests(APITestCase):
    """یک صفحهٔ کوچکِ واقعی (با قلمِ لاتین؛ چون OCR ِ فارسی در CI نباید قاعدهٔ سخت شود) از آغاز تا پایان: بارگذاری ⇒ runner ⇒ mv2code ⇒ (مرورگر) ⇒ امتیاز."""

    databases = {"default", "studio"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eng = _real_engine()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-img2code-real-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.override = override_settings(NM_DATA_DIR=self.tmp / "data", WORKSPACES_ROOT=self.tmp / "work")
        self.override.enable()
        self.addCleanup(self.override.disable)
        (self.tmp / "work").mkdir(parents=True, exist_ok=True)
        self.user = User.objects.create_user("i2c-real", password="x", is_staff=True)
        self.store = Store.objects.create(owner=self.user, name="واقعی")
        self.client.force_authenticate(self.user)

    def page_png(self) -> bytes:
        im = Image.new("RGB", (900, 560), (241, 245, 249))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 900, 70], fill=(255, 255, 255))
        big, small = ImageFont.load_default(size=44), ImageFont.load_default(size=22)
        d.text((60, 14), "ShopName", font=small, fill=(27, 110, 194))
        d.text((220, 140), "Welcome to the shop", font=big, fill=(15, 42, 74))
        d.text((250, 215), "Everything you need to get started", font=small, fill=(65, 80, 106))
        d.rounded_rectangle([330, 300, 570, 360], radius=14, fill=(27, 110, 194))
        d.text((385, 318), "Get started", font=small, fill=(255, 255, 255))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    def test_real_small_conversion_end_to_end(self):
        if not self.eng.get("ready") or not self.eng.get("ocr"):
            self.skipTest("mv2code/Tesseract روی این ماشین نیست: %s" % self.eng.get("messages"))
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post("/api/v1/stores/%d/image-to-code/" % self.store.pk, {"image": upload(self.page_png()), "mode": "responsive", "lang": "en"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        conv = Conversion.objects.get(pk=r.json()["item"]["id"])
        self.assertEqual(conv.state, "READY", conv.error)
        tree = json.loads((conv.out_dir / "tree.json").read_text(encoding="utf-8"))
        roles = []

        def walk(n):
            roles.append(n["role"])
            for c in n.get("children", []):
                walk(c)
        walk(tree)
        self.assertGreaterEqual(len(roles), 4)
        html = (conv.out_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("<html", html)
        self.assertIn("Welcome", html)                               # متنِ واقعی، نه تصویرِ نوشته
        self.assertGreater(conv.report["text_lines"], 2)
        if self.eng.get("compare_ok"):
            self.assertTrue((conv.out_dir / "rendered.png").exists())
            self.assertTrue({s["key"] for s in conv.scores} >= {"ssim", "editable"})
            self.assertGreater(conv.raw_scores["ssim"], 0.5)
        # و درختِ واقعی هم به پیش‌نویسِ سایت‌ساز می‌رسد
        r2 = self.client.post("/api/v1/stores/%d/image-to-code/%d/site-draft/" % (self.store.pk, conv.pk), {}, format="json")
        self.assertEqual(r2.status_code, 201, r2.content)
        d = Design.objects.get(page_id=r2.json()["page_id"])
        self.assertIn("Welcome to the shop", json.dumps(d.draft, ensure_ascii=False))



SLEEPER = """import time
time.sleep(60)
"""
HOG = """x = bytearray(900 * 1024 * 1024)
print('RESULT {"ok": true}')
"""
NOISY = """print('warning: something')
print('RESULT {"ok": true, "n": 3}')
"""


class ProcessCapTests(APITestCase):
    """سقفِ زمان/حافظه و لغو روی پردازهٔ واقعی (با یک runner ِ ساختگی که می‌خوابد یا حافظه می‌خورد؛ بدونِ نیاز به موتور)."""

    def dummy(self, body):
        root = Path(tempfile.mkdtemp(prefix="nm-img2code-dummy-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "apps" / "img2code").mkdir(parents=True)
        (root / "apps" / "__init__.py").write_text("")
        (root / "apps" / "img2code" / "__init__.py").write_text("")
        (root / "apps" / "img2code" / "runner.py").write_text(body)
        return root

    def test_time_cap_kills_the_process(self):
        import time
        root = self.dummy(SLEEPER)
        t0 = time.monotonic()
        with mock.patch.object(services, "BACKEND_DIR", root):
            res = services.run_process(["probe"], timeout=1.0)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual((res["ok"], res["error"]), (False, "timeout"))
        self.assertIn("زمان", res["message"])

    def test_memory_cap_stops_a_runaway_process(self):
        if services.fcntl is None:
            self.skipTest("فقط لینوکس")
        root = self.dummy(HOG)
        with mock.patch.object(services, "BACKEND_DIR", root):
            res = services.run_process(["probe"], timeout=30, mem=400 * 1024 * 1024)
        self.assertFalse(res["ok"])
        self.assertIn(res["error"], ("crashed", "killed"))

    def test_cancel_tick_kills_the_process(self):
        import time
        root = self.dummy(SLEEPER)
        t0 = time.monotonic()
        with mock.patch.object(services, "BACKEND_DIR", root):
            res = services.run_process(["probe"], timeout=60, tick=lambda elapsed: True)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(res["error"], "cancelled")

    def test_result_line_is_parsed_even_with_log_noise(self):
        root = self.dummy(NOISY)
        with mock.patch.object(services, "BACKEND_DIR", root):
            self.assertEqual(services.run_process(["probe"], timeout=30), {"ok": True, "n": 3})
